#!/usr/bin/env python3
"""
Codex token usage analyzer.

Analyzes Codex JSONL session logs from:
- ~/.codex/sessions
- ~/.codex/archived_sessions

It groups sessions by project, reports token usage, and extracts user prompts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def parse_optional_int_env(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value or None


def parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_lang_code(value: str | None) -> str:
    if not value:
        return "en"
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "en": "en",
        "en-us": "en",
        "en-gb": "en",
        "english": "en",
        "pt": "pt-br",
        "pt-br": "pt-br",
        "ptbr": "pt-br",
        "pt-pt": "pt-pt",
        "ptpt": "pt-pt",
        "es": "es",
        "es-es": "es",
        "spanish": "es",
    }
    return aliases.get(normalized, "en")


TRANSLATIONS = {
    "en": {
        "app_description": "Analyze local Codex session logs and generate usage reports.",
        "error_prefix": "Error",
        "table_project": "Project",
        "table_sessions": "Sessions",
        "table_total_tokens": "Total Tokens",
        "table_subagents": "Subagents",
        "col_session": "Session",
        "col_first_prompt": "First Prompt",
        "col_total": "Total",
        "col_input": "Input",
        "col_cached_input": "Cached Input",
        "col_output": "Output",
        "col_reasoning": "Reasoning",
        "col_parent_session": "Parent Session",
        "col_descendant_subagents": "Descendant Subagents",
        "col_descendant_tokens": "Descendant Tokens",
        "col_overhead_vs_parent": "Overhead vs Parent",
        "col_parent_tokens": "Parent Tokens",
        "col_subagent": "Subagent",
        "col_role": "Role",
        "col_subagent_sessions": "Subagent Sessions",
        "col_subagent_tokens": "Subagent Tokens",
        "col_originator": "Originator",
        "col_agent_role": "Agent Role",
        "col_workspace_kind": "Workspace Kind",
        "col_base_instr_chars": "Base Instr Chars",
        "col_max_turn_instr_chars": "Max Turn Instr Chars",
        "col_combined_chars": "Combined Chars",
        "col_est_tokens": "Est. Tokens",
        "date_range_since": "Since {date}",
        "date_range_all_time": "All time",
        "report_title": "# Codex Token Usage Analysis",
        "report_generated": "Generated: {now} | Range: {date_range}",
        "report_grand_totals": "## Grand Totals",
        "report_projects": "- **Projects**: {count}",
        "report_sessions": "- **Sessions**: {count}",
        "report_total_tokens": "- **Total tokens**: {value}",
        "report_input": "  - Input: {value}",
        "report_cached_input": "  - Cached input: {value}",
        "report_output": "  - Output: {value}",
        "report_reasoning_output": "  - Reasoning output: {value}",
        "report_subagent_sessions": "- **Subagent sessions**: {count} ({tokens} tokens)",
        "report_subagents_missing_parent": "- **Subagents with missing parent in range**: {count}",
        "report_by_project": "## By Project",
        "report_most_costly_sessions": "## Most Costly Sessions",
        "report_session_title": "### {index}. {project} - {tokens} tokens",
        "report_session_label": "- **Session**: `{session_id}`",
        "report_started_label": "- **Started**: {value}",
        "report_cwd_label": "- **CWD**: `{value}`",
        "report_direct_subagents_label": "- **Direct subagents**: {count}",
        "report_tokens_label": "- **Tokens**: input={input}, cached_input={cached_input}, output={output}, reasoning={reasoning}",
        "report_first_prompt_label": "- **First prompt**:",
        "report_highest_ratios": "## Highest Input/Output Ratios",
        "report_subagent_overhead_hotspots": "## Subagent Overhead Hotspots",
        "report_most_costly_subagents": "## Most Costly Subagents",
        "report_subagent_usage_by_project": "## Subagent Usage By Project",
        "report_usage_by_originator": "## Usage By Originator",
        "report_usage_by_agent_role": "## Usage By Agent Role",
        "report_usage_by_workspace_kind": "## Usage By Workspace Kind",
        "report_instruction_heavy": "## Most Instruction-Heavy Sessions",
        "report_likely_savings": "## Likely Savings Opportunities",
        "insight_subagent_cost": "- Subagent usage is a major cost center: {subagent_tokens} of {grand_total} total tokens ({share}) are in subagent sessions.",
        "insight_context_replay": "- Context replay dominates output: input/output is {input_output_ratio} and cached-input/output is {cached_output_ratio} across the whole report window.",
        "insight_top_sessions_share": "- A small number of sessions dominate spend: the top 5 non-subagent sessions account for {tokens} tokens ({share} of total usage).",
        "insight_hotspot": "- The largest subagent hotspot is `{session_id}` in {project}: {descendant_count} descendant subagents consumed {descendant_tokens} tokens, equal to {overhead_ratio} of the parent session's own token count.",
        "insight_instruction_heavy": "- The heaviest static instruction payload observed was in `{session_id}` ({project}) at {instruction_chars} characters, or about ~{instruction_tokens} tokens before any repo/file context was added.",
        "prompts_title": "# Prompts: {project}",
        "prompts_summary": "{prompt_count} prompts across {session_count} sessions",
        "prompts_session_item": "## {index}. [{timestamp}] Session `{session_id}`",
        "unknown": "unknown",
        "console_scanning": "Scanning Codex sessions...",
        "console_found_projects": "Found {count} projects",
        "console_total_summary": "Total: {tokens} tokens across {sessions} sessions in {projects} projects",
        "console_top_10": "Top 10 costliest sessions:",
        "console_no_prompt": "no prompt captured",
        "console_full_report": "Full report: {path}",
        "console_json_report": "JSON report: {path}",
        "console_prompts": "Prompts: {path}",
    },
    "pt-br": {
        "app_description": "Analisa logs locais de sessões do Codex e gera relatórios de uso.",
        "error_prefix": "Erro",
        "table_project": "Projeto",
        "table_sessions": "Sessões",
        "table_total_tokens": "Tokens Totais",
        "table_subagents": "Subagentes",
        "col_session": "Sessão",
        "col_first_prompt": "Primeiro Prompt",
        "col_total": "Total",
        "col_input": "Entrada",
        "col_cached_input": "Entrada em Cache",
        "col_output": "Saída",
        "col_reasoning": "Raciocínio",
        "col_parent_session": "Sessão Pai",
        "col_descendant_subagents": "Subagentes Descendentes",
        "col_descendant_tokens": "Tokens Descendentes",
        "col_overhead_vs_parent": "Overhead vs Pai",
        "col_parent_tokens": "Tokens da Sessão Pai",
        "col_subagent": "Subagente",
        "col_role": "Função",
        "col_subagent_sessions": "Sessões de Subagente",
        "col_subagent_tokens": "Tokens de Subagente",
        "col_originator": "Originador",
        "col_agent_role": "Função do Agente",
        "col_workspace_kind": "Tipo de Workspace",
        "col_base_instr_chars": "Chars de Instr. Base",
        "col_max_turn_instr_chars": "Máx. Chars de Instr. por Turno",
        "col_combined_chars": "Chars Combinados",
        "col_est_tokens": "Tokens Est.",
        "date_range_since": "Desde {date}",
        "date_range_all_time": "Todo o período",
        "report_title": "# Análise de Uso de Tokens do Codex",
        "report_generated": "Gerado em: {now} | Período: {date_range}",
        "report_grand_totals": "## Totais Gerais",
        "report_projects": "- **Projetos**: {count}",
        "report_sessions": "- **Sessões**: {count}",
        "report_total_tokens": "- **Total de tokens**: {value}",
        "report_input": "  - Entrada: {value}",
        "report_cached_input": "  - Entrada em cache: {value}",
        "report_output": "  - Saída: {value}",
        "report_reasoning_output": "  - Saída de raciocínio: {value}",
        "report_subagent_sessions": "- **Sessões de subagente**: {count} ({tokens} tokens)",
        "report_subagents_missing_parent": "- **Subagentes com sessão-pai fora do período**: {count}",
        "report_by_project": "## Por Projeto",
        "report_most_costly_sessions": "## Sessões Mais Caras",
        "report_session_title": "### {index}. {project} - {tokens} tokens",
        "report_session_label": "- **Sessão**: `{session_id}`",
        "report_started_label": "- **Iniciada**: {value}",
        "report_cwd_label": "- **CWD**: `{value}`",
        "report_direct_subagents_label": "- **Subagentes diretos**: {count}",
        "report_tokens_label": "- **Tokens**: entrada={input}, entrada_em_cache={cached_input}, saída={output}, raciocínio={reasoning}",
        "report_first_prompt_label": "- **Primeiro prompt**:",
        "report_highest_ratios": "## Maiores Razões Entrada/Saída",
        "report_subagent_overhead_hotspots": "## Pontos Críticos de Overhead de Subagentes",
        "report_most_costly_subagents": "## Subagentes Mais Caros",
        "report_subagent_usage_by_project": "## Uso de Subagentes por Projeto",
        "report_usage_by_originator": "## Uso por Originador",
        "report_usage_by_agent_role": "## Uso por Função de Agente",
        "report_usage_by_workspace_kind": "## Uso por Tipo de Workspace",
        "report_instruction_heavy": "## Sessões com Maior Carga de Instruções",
        "report_likely_savings": "## Oportunidades de Economia",
        "insight_subagent_cost": "- O uso de subagentes é um grande centro de custo: {subagent_tokens} de {grand_total} tokens totais ({share}) estão em sessões de subagente.",
        "insight_context_replay": "- A repetição de contexto domina a saída: entrada/saída = {input_output_ratio} e cache/saída = {cached_output_ratio} em todo o período analisado.",
        "insight_top_sessions_share": "- Um pequeno número de sessões concentra o gasto: as 5 maiores sessões não subagente somam {tokens} tokens ({share} do uso total).",
        "insight_hotspot": "- O maior hotspot de subagente é `{session_id}` em {project}: {descendant_count} subagentes descendentes consumiram {descendant_tokens} tokens, equivalente a {overhead_ratio} do total da sessão pai.",
        "insight_instruction_heavy": "- A maior carga estática de instruções foi observada em `{session_id}` ({project}), com {instruction_chars} caracteres, cerca de ~{instruction_tokens} tokens antes de adicionar contexto de repositório/arquivos.",
        "prompts_title": "# Prompts: {project}",
        "prompts_summary": "{prompt_count} prompts em {session_count} sessões",
        "prompts_session_item": "## {index}. [{timestamp}] Sessão `{session_id}`",
        "unknown": "desconhecido",
        "console_scanning": "Analisando sessões do Codex...",
        "console_found_projects": "Encontrados {count} projetos",
        "console_total_summary": "Total: {tokens} tokens em {sessions} sessões de {projects} projetos",
        "console_top_10": "Top 10 sessões mais caras:",
        "console_no_prompt": "nenhum prompt capturado",
        "console_full_report": "Relatório completo: {path}",
        "console_json_report": "Relatório JSON: {path}",
        "console_prompts": "Prompts: {path}",
    },
    "pt-pt": {
        "app_description": "Analisa registos locais de sessões do Codex e gera relatórios de utilização.",
        "error_prefix": "Erro",
        "table_project": "Projeto",
        "table_sessions": "Sessões",
        "table_total_tokens": "Tokens Totais",
        "table_subagents": "Subagentes",
        "col_session": "Sessão",
        "col_first_prompt": "Primeiro Prompt",
        "col_total": "Total",
        "col_input": "Entrada",
        "col_cached_input": "Entrada em Cache",
        "col_output": "Saída",
        "col_reasoning": "Raciocínio",
        "col_parent_session": "Sessão Pai",
        "col_descendant_subagents": "Subagentes Descendentes",
        "col_descendant_tokens": "Tokens Descendentes",
        "col_overhead_vs_parent": "Overhead vs Pai",
        "col_parent_tokens": "Tokens da Sessão Pai",
        "col_subagent": "Subagente",
        "col_role": "Função",
        "col_subagent_sessions": "Sessões de Subagente",
        "col_subagent_tokens": "Tokens de Subagente",
        "col_originator": "Originador",
        "col_agent_role": "Função do Agente",
        "col_workspace_kind": "Tipo de Workspace",
        "col_base_instr_chars": "Chars de Instr. Base",
        "col_max_turn_instr_chars": "Máx. Chars de Instr. por Turno",
        "col_combined_chars": "Chars Combinados",
        "col_est_tokens": "Tokens Est.",
        "date_range_since": "Desde {date}",
        "date_range_all_time": "Todo o período",
        "report_title": "# Análise de Utilização de Tokens do Codex",
        "report_generated": "Gerado em: {now} | Período: {date_range}",
        "report_grand_totals": "## Totais Gerais",
        "report_projects": "- **Projetos**: {count}",
        "report_sessions": "- **Sessões**: {count}",
        "report_total_tokens": "- **Total de tokens**: {value}",
        "report_input": "  - Entrada: {value}",
        "report_cached_input": "  - Entrada em cache: {value}",
        "report_output": "  - Saída: {value}",
        "report_reasoning_output": "  - Saída de raciocínio: {value}",
        "report_subagent_sessions": "- **Sessões de subagente**: {count} ({tokens} tokens)",
        "report_subagents_missing_parent": "- **Subagentes com sessão-pai fora do período**: {count}",
        "report_by_project": "## Por Projeto",
        "report_most_costly_sessions": "## Sessões Mais Dispendiosas",
        "report_session_title": "### {index}. {project} - {tokens} tokens",
        "report_session_label": "- **Sessão**: `{session_id}`",
        "report_started_label": "- **Iniciada**: {value}",
        "report_cwd_label": "- **CWD**: `{value}`",
        "report_direct_subagents_label": "- **Subagentes diretos**: {count}",
        "report_tokens_label": "- **Tokens**: entrada={input}, entrada_em_cache={cached_input}, saída={output}, raciocínio={reasoning}",
        "report_first_prompt_label": "- **Primeiro prompt**:",
        "report_highest_ratios": "## Maiores Rácios Entrada/Saída",
        "report_subagent_overhead_hotspots": "## Pontos Críticos de Overhead de Subagentes",
        "report_most_costly_subagents": "## Subagentes Mais Dispendiosos",
        "report_subagent_usage_by_project": "## Uso de Subagentes por Projeto",
        "report_usage_by_originator": "## Uso por Originador",
        "report_usage_by_agent_role": "## Uso por Função de Agente",
        "report_usage_by_workspace_kind": "## Uso por Tipo de Workspace",
        "report_instruction_heavy": "## Sessões com Maior Carga de Instruções",
        "report_likely_savings": "## Oportunidades de Poupança",
        "insight_subagent_cost": "- O uso de subagentes é um grande centro de custo: {subagent_tokens} de {grand_total} tokens totais ({share}) estão em sessões de subagente.",
        "insight_context_replay": "- A repetição de contexto domina a saída: entrada/saída = {input_output_ratio} e cache/saída = {cached_output_ratio} em todo o período analisado.",
        "insight_top_sessions_share": "- Um pequeno número de sessões concentra o custo: as 5 maiores sessões não subagente totalizam {tokens} tokens ({share} do uso total).",
        "insight_hotspot": "- O maior hotspot de subagente é `{session_id}` em {project}: {descendant_count} subagentes descendentes consumiram {descendant_tokens} tokens, equivalente a {overhead_ratio} do total da sessão pai.",
        "insight_instruction_heavy": "- A maior carga estática de instruções foi observada em `{session_id}` ({project}), com {instruction_chars} caracteres, cerca de ~{instruction_tokens} tokens antes de adicionar contexto de repositório/ficheiros.",
        "prompts_title": "# Prompts: {project}",
        "prompts_summary": "{prompt_count} prompts em {session_count} sessões",
        "prompts_session_item": "## {index}. [{timestamp}] Sessão `{session_id}`",
        "unknown": "desconhecido",
        "console_scanning": "A analisar sessões do Codex...",
        "console_found_projects": "Encontrados {count} projetos",
        "console_total_summary": "Total: {tokens} tokens em {sessions} sessões de {projects} projetos",
        "console_top_10": "Top 10 sessões mais dispendiosas:",
        "console_no_prompt": "nenhum prompt capturado",
        "console_full_report": "Relatório completo: {path}",
        "console_json_report": "Relatório JSON: {path}",
        "console_prompts": "Prompts: {path}",
    },
    "es": {
        "app_description": "Analiza registros locales de sesiones de Codex y genera informes de uso.",
        "error_prefix": "Error",
        "table_project": "Proyecto",
        "table_sessions": "Sesiones",
        "table_total_tokens": "Tokens Totales",
        "table_subagents": "Subagentes",
        "col_session": "Sesión",
        "col_first_prompt": "Primer Prompt",
        "col_total": "Total",
        "col_input": "Entrada",
        "col_cached_input": "Entrada en Caché",
        "col_output": "Salida",
        "col_reasoning": "Razonamiento",
        "col_parent_session": "Sesión Padre",
        "col_descendant_subagents": "Subagentes Descendientes",
        "col_descendant_tokens": "Tokens Descendientes",
        "col_overhead_vs_parent": "Sobrecarga vs Padre",
        "col_parent_tokens": "Tokens de la Sesión Padre",
        "col_subagent": "Subagente",
        "col_role": "Rol",
        "col_subagent_sessions": "Sesiones de Subagente",
        "col_subagent_tokens": "Tokens de Subagente",
        "col_originator": "Originador",
        "col_agent_role": "Rol del Agente",
        "col_workspace_kind": "Tipo de Workspace",
        "col_base_instr_chars": "Chars de Instr. Base",
        "col_max_turn_instr_chars": "Máx. Chars de Instr. por Turno",
        "col_combined_chars": "Chars Combinados",
        "col_est_tokens": "Tokens Est.",
        "date_range_since": "Desde {date}",
        "date_range_all_time": "Todo el período",
        "report_title": "# Análisis de Uso de Tokens de Codex",
        "report_generated": "Generado: {now} | Rango: {date_range}",
        "report_grand_totals": "## Totales Generales",
        "report_projects": "- **Proyectos**: {count}",
        "report_sessions": "- **Sesiones**: {count}",
        "report_total_tokens": "- **Total de tokens**: {value}",
        "report_input": "  - Entrada: {value}",
        "report_cached_input": "  - Entrada en caché: {value}",
        "report_output": "  - Salida: {value}",
        "report_reasoning_output": "  - Salida de razonamiento: {value}",
        "report_subagent_sessions": "- **Sesiones de subagente**: {count} ({tokens} tokens)",
        "report_subagents_missing_parent": "- **Subagentes con sesión padre fuera del rango**: {count}",
        "report_by_project": "## Por Proyecto",
        "report_most_costly_sessions": "## Sesiones Más Costosas",
        "report_session_title": "### {index}. {project} - {tokens} tokens",
        "report_session_label": "- **Sesión**: `{session_id}`",
        "report_started_label": "- **Inicio**: {value}",
        "report_cwd_label": "- **CWD**: `{value}`",
        "report_direct_subagents_label": "- **Subagentes directos**: {count}",
        "report_tokens_label": "- **Tokens**: entrada={input}, entrada_en_caché={cached_input}, salida={output}, razonamiento={reasoning}",
        "report_first_prompt_label": "- **Primer prompt**:",
        "report_highest_ratios": "## Mayores Ratios Entrada/Salida",
        "report_subagent_overhead_hotspots": "## Puntos Críticos de Sobrecarga de Subagentes",
        "report_most_costly_subagents": "## Subagentes Más Costosos",
        "report_subagent_usage_by_project": "## Uso de Subagentes por Proyecto",
        "report_usage_by_originator": "## Uso por Originador",
        "report_usage_by_agent_role": "## Uso por Rol de Agente",
        "report_usage_by_workspace_kind": "## Uso por Tipo de Workspace",
        "report_instruction_heavy": "## Sesiones con Mayor Carga de Instrucciones",
        "report_likely_savings": "## Oportunidades Probables de Ahorro",
        "insight_subagent_cost": "- El uso de subagentes es un gran centro de coste: {subagent_tokens} de {grand_total} tokens totales ({share}) están en sesiones de subagente.",
        "insight_context_replay": "- La repetición de contexto domina la salida: entrada/salida = {input_output_ratio} y caché/salida = {cached_output_ratio} en todo el período analizado.",
        "insight_top_sessions_share": "- Un pequeño número de sesiones concentra el gasto: las 5 mayores sesiones no subagente suman {tokens} tokens ({share} del uso total).",
        "insight_hotspot": "- El mayor hotspot de subagente es `{session_id}` en {project}: {descendant_count} subagentes descendientes consumieron {descendant_tokens} tokens, equivalente a {overhead_ratio} del total de la sesión padre.",
        "insight_instruction_heavy": "- La mayor carga estática de instrucciones se observó en `{session_id}` ({project}), con {instruction_chars} caracteres, cerca de ~{instruction_tokens} tokens antes de añadir contexto de repositorio/archivos.",
        "prompts_title": "# Prompts: {project}",
        "prompts_summary": "{prompt_count} prompts en {session_count} sesiones",
        "prompts_session_item": "## {index}. [{timestamp}] Sesión `{session_id}`",
        "unknown": "desconocido",
        "console_scanning": "Escaneando sesiones de Codex...",
        "console_found_projects": "Se encontraron {count} proyectos",
        "console_total_summary": "Total: {tokens} tokens en {sessions} sesiones de {projects} proyectos",
        "console_top_10": "Top 10 sesiones más costosas:",
        "console_no_prompt": "no se capturó ningún prompt",
        "console_full_report": "Reporte completo: {path}",
        "console_json_report": "Reporte JSON: {path}",
        "console_prompts": "Prompts: {path}",
    },
}


def tr(key: str, **kwargs: Any) -> str:
    lang_map = TRANSLATIONS.get(REPORT_LANG, TRANSLATIONS["en"])
    template = lang_map.get(key, TRANSLATIONS["en"].get(key, key))
    return template.format(**kwargs)


CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
SESSION_DIRS = [
    CODEX_HOME / "sessions",
    CODEX_HOME / "archived_sessions",
]
OUTPUT_DIR_ENV = os.environ.get("OUTPUT_DIR")
REPORT_LANG = normalize_lang_code(os.environ.get("REPORT_LANG"))


def build_run_folder_name(lang_code: str | None = None) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    normalized_lang = normalize_lang_code(lang_code)
    return f"{normalized_lang}-{timestamp}"


def default_output_dir(lang_code: str | None = None) -> Path:
    return Path.cwd() / "reports" / build_run_folder_name(lang_code)


def resolve_output_dir(raw_output_dir: str | None, lang_code: str) -> Path:
    if not raw_output_dir:
        return default_output_dir(lang_code)

    output_dir = Path(raw_output_dir).expanduser()
    folder_name = output_dir.name.strip().lower().replace("_", "-")
    parent_name = output_dir.parent.name.strip().lower().replace("_", "-")
    normalized_lang = normalize_lang_code(lang_code)

    if folder_name == "reports":
        return output_dir / build_run_folder_name(normalized_lang)
    if folder_name == normalized_lang and parent_name == "reports":
        return output_dir.parent / build_run_folder_name(normalized_lang)
    return output_dir


OUTPUT_DIR = resolve_output_dir(OUTPUT_DIR_ENV, REPORT_LANG)

# Filter: only include sessions that started within the last N days (None = all time)
SINCE_DAYS = parse_optional_int_env("SINCE_DAYS")
SINCE_DATE = os.environ.get("SINCE_DATE")  # e.g. "2026-03-30"
REDACT_PROMPTS = parse_bool_env("REDACT_PROMPTS", default=False)
WRITE_JSON = parse_bool_env("WRITE_JSON", default=True)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_cutoff() -> datetime | None:
    """Return a UTC-aware datetime cutoff, or None for all time."""
    if SINCE_DATE:
        return datetime.strptime(SINCE_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if SINCE_DAYS:
        return datetime.now(timezone.utc) - timedelta(days=SINCE_DAYS)
    return None


def format_date_range(cutoff: datetime | None) -> str:
    if cutoff:
        return tr("date_range_since", date=cutoff.strftime("%Y-%m-%d"))
    return tr("date_range_all_time")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=tr("app_description")
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=SINCE_DAYS,
        help="Only include sessions started within the last N days.",
    )
    parser.add_argument(
        "--since-date",
        default=SINCE_DATE,
        help="Only include sessions started on/after YYYY-MM-DD.",
    )
    parser.add_argument(
        "--codex-home",
        default=str(CODEX_HOME),
        help="Path to Codex home directory (default: ~/.codex).",
    )
    parser.add_argument(
        "--output-dir",
        default=OUTPUT_DIR_ENV,
        help="Directory for generated reports.",
    )
    parser.add_argument(
        "--redact-prompts",
        action=argparse.BooleanOptionalAction,
        default=REDACT_PROMPTS,
        help="Redact prompt text in console output and generated reports.",
    )
    parser.add_argument(
        "--json",
        dest="write_json",
        action=argparse.BooleanOptionalAction,
        default=WRITE_JSON,
        help="Generate token_report.json in addition to markdown report.",
    )
    parser.add_argument(
        "--lang",
        default=REPORT_LANG,
        help="Report/console language: en, pt-br, pt-pt, es.",
    )
    return parser.parse_args(argv)


def configure_runtime(args: argparse.Namespace) -> None:
    global CODEX_HOME
    global SESSION_DIRS
    global OUTPUT_DIR
    global SINCE_DAYS
    global SINCE_DATE
    global REDACT_PROMPTS
    global WRITE_JSON
    global REPORT_LANG

    if args.since_days is not None and args.since_days < 0:
        raise ValueError("--since-days must be >= 0")
    if args.since_date:
        try:
            datetime.strptime(str(args.since_date), "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("--since-date must be in YYYY-MM-DD format") from exc

    CODEX_HOME = Path(args.codex_home).expanduser()
    SESSION_DIRS = [
        CODEX_HOME / "sessions",
        CODEX_HOME / "archived_sessions",
    ]
    REPORT_LANG = normalize_lang_code(args.lang)
    OUTPUT_DIR = resolve_output_dir(args.output_dir, REPORT_LANG)
    SINCE_DAYS = args.since_days
    SINCE_DATE = args.since_date
    REDACT_PROMPTS = bool(args.redact_prompts)
    WRITE_JSON = bool(args.write_json)


def format_tokens(value: int) -> str:
    return f"{value:,}"


def format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 999:
        return f"{value:,.0f}x"
    return f"{value:.1f}x"


def format_percent(value: float) -> str:
    return f"{value:.1f}%"


def sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return " ".join(text.split())


def truncate_text(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def format_table_cell(value: Any, limit: int | None = None) -> str:
    text = sanitize_text(value)
    if limit is not None:
        text = truncate_text(text, limit)
    return text.replace("|", "\\|")


def short_session_id(session_id: str | None, size: int = 8) -> str:
    sid = sanitize_text(session_id) or "?"
    if len(sid) <= size:
        return sid
    return f"{sid[:size]}..."


def make_safe_filename(name: str, fallback: str = "unknown", limit: int = 80) -> str:
    safe_chars = []
    for char in name:
        if char.isalnum() or char in ("-", "_", "."):
            safe_chars.append(char)
        else:
            safe_chars.append("_")
    safe = "".join(safe_chars).strip("._")
    if not safe:
        safe = fallback
    return safe[:limit]


def normalize_path_for_compare(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("\\", "/").rstrip("/").lower()


def get_terminal_columns(default: int = 120) -> int:
    try:
        return shutil.get_terminal_size(fallback=(default, 24)).columns
    except OSError:
        return default


def iter_session_files() -> list[Path]:
    files: list[Path] = []
    for directory in SESSION_DIRS:
        if directory.is_dir():
            files.extend(sorted(directory.rglob("*.jsonl")))
    return files


def derive_project_name(meta: dict[str, Any]) -> str:
    git_info = meta.get("git") or {}
    repository_url = git_info.get("repository_url")
    if isinstance(repository_url, str) and repository_url:
        parsed = urlparse(repository_url)
        name = Path(parsed.path).name
        if name.endswith(".git"):
            name = name[:-4]
        if name:
            return name

    cwd = meta.get("cwd")
    if isinstance(cwd, str) and cwd:
        path = Path(cwd)
        if path.name:
            return path.name

    return "unknown"


def normalize_source(source: Any) -> str:
    if isinstance(source, str) and source:
        return source
    if isinstance(source, dict) and "subagent" in source:
        return "subagent"
    if source is None:
        return "unknown"
    return str(source)


def classify_workspace(cwd: str | None) -> str:
    if not cwd:
        return "unknown"
    normalized = normalize_path_for_compare(cwd)
    codex_home_normalized = normalize_path_for_compare(str(CODEX_HOME))
    worktree_marker = f"{codex_home_normalized}/worktrees"
    if normalized.startswith(worktree_marker):
        return "codex worktree"
    return "repo root/other"


def is_subagent_session(meta: dict[str, Any]) -> bool:
    source = meta.get("source")
    return isinstance(source, dict) and "subagent" in source


def get_parent_session_id(meta: dict[str, Any]) -> str | None:
    if meta.get("forked_from_id"):
        return meta["forked_from_id"]

    source = meta.get("source")
    if isinstance(source, dict):
        parent_id = (
            source.get("subagent", {})
            .get("thread_spawn", {})
            .get("parent_thread_id")
        )
        if isinstance(parent_id, str) and parent_id:
            return parent_id

    return None


def get_subagent_label(meta: dict[str, Any]) -> str:
    task_name = meta.get("agent_path")
    if isinstance(task_name, str) and task_name:
        return task_name
    nickname = meta.get("agent_nickname")
    if isinstance(nickname, str) and nickname:
        return nickname
    role = meta.get("agent_role")
    if isinstance(role, str) and role:
        return role
    return "subagent"


def session_in_range(session: dict[str, Any], cutoff: datetime | None) -> bool:
    if not cutoff:
        return True
    ts = parse_iso_datetime(session.get("timestamp_start"))
    return ts is None or ts >= cutoff


def estimate_instruction_tokens(char_count: int) -> int:
    # Rough heuristic for Latin text. Reported as an estimate only.
    return round(char_count / 4)


def normalize_prompt_for_display(text: str) -> str:
    cleaned = sanitize_text(text)
    # Keep prompt excerpts readable in terminal and markdown tables.
    cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 ", cleaned)
    # Handle malformed markdown links that start with URLs but never close.
    cleaned = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\s+and\b", r"\1 ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+", r"\1 ", cleaned)
    # Handle malformed markdown links that miss the closing parenthesis.
    cleaned = re.sub(r"\[([^\]]+)\]\(", r"\1 ", cleaned)
    cleaned = cleaned.replace("# Context from my IDE setup:", "Context:")
    cleaned = cleaned.replace("## Active file:", "Active file:")
    cleaned = cleaned.replace("## Open tabs:", "Open tabs:")
    cleaned = cleaned.replace("## My request for Codex:", "User request:")
    cleaned = cleaned.replace("# Files mentioned by the user:", "Files:")
    cleaned = cleaned.replace("## Files mentioned by the user:", "Files:")
    cleaned = re.sub(r"(^| )#{1,6}\s+", r"\1", cleaned)
    return " ".join(cleaned.split())


def redact_prompt_text(text: str) -> str:
    length = len(sanitize_text(text))
    return f"[redacted prompt: {length} chars]"


def get_first_prompt_text(session: dict[str, Any], limit: int = 160) -> str:
    if not session["prompts"]:
        return ""
    first_prompt = session["prompts"][0]["text"]
    if REDACT_PROMPTS:
        return truncate_text(redact_prompt_text(first_prompt), limit)
    return truncate_text(normalize_prompt_for_display(first_prompt), limit)


def compute_input_output_ratio(session: dict[str, Any]) -> float | None:
    usage = session.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    output_tokens = usage.get("output_tokens", 0)
    if output_tokens <= 0:
        return None
    return usage.get("input_tokens", 0) / output_tokens


def compute_cached_input_to_output_ratio(session: dict[str, Any]) -> float | None:
    usage = session.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    output_tokens = usage.get("output_tokens", 0)
    if output_tokens <= 0:
        return None
    return usage.get("cached_input_tokens", 0) / output_tokens


def compute_cached_output_ratio(session: dict[str, Any]) -> float | None:
    # Backward-compatible alias for old name.
    return compute_cached_input_to_output_ratio(session)


def get_cached_input_to_output_ratio(session: dict[str, Any]) -> float | None:
    return session.get("cached_input_to_output_ratio", session.get("cached_output_ratio"))


def parse_session(jsonl_path: Path) -> dict[str, Any] | None:
    try:
        lines = jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    if not lines:
        return None

    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError:
        return None

    if first.get("type") != "session_meta":
        return None

    meta = first.get("payload", {})
    base_instruction_text = (
        (meta.get("base_instructions") or {}).get("text")
        if isinstance(meta.get("base_instructions"), dict)
        else ""
    )
    base_instruction_chars = (
        len(base_instruction_text) if isinstance(base_instruction_text, str) else 0
    )
    usage_total = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }
    prompts: list[dict[str, Any]] = []
    final_message = None
    max_user_instruction_chars = 0
    turn_count = 0

    for line in lines[1:]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        obj_type = obj.get("type")

        if obj_type == "turn_context":
            turn_count += 1
            payload = obj.get("payload", {})
            user_instructions = payload.get("user_instructions")
            if isinstance(user_instructions, str):
                max_user_instruction_chars = max(
                    max_user_instruction_chars, len(user_instructions)
                )
            continue

        if obj_type != "event_msg":
            continue

        payload = obj.get("payload", {})
        payload_type = payload.get("type")

        if payload_type == "token_count":
            info = payload.get("info") or {}
            totals = info.get("total_token_usage") or {}
            if totals:
                usage_total = {
                    "input_tokens": int(totals.get("input_tokens", 0)),
                    "cached_input_tokens": int(totals.get("cached_input_tokens", 0)),
                    "output_tokens": int(totals.get("output_tokens", 0)),
                    "reasoning_output_tokens": int(
                        totals.get("reasoning_output_tokens", 0)
                    ),
                    "total_tokens": int(totals.get("total_tokens", 0)),
                }

        elif payload_type == "user_message":
            text = payload.get("message", "")
            if text:
                prompts.append(
                    {
                        "text": text,
                        "timestamp": obj.get("timestamp"),
                    }
                )

        elif payload_type == "task_complete":
            final_message = payload.get("last_agent_message")

    instruction_chars = base_instruction_chars + max_user_instruction_chars

    cached_input_to_output_ratio = compute_cached_input_to_output_ratio(
        {"usage": usage_total, "prompts": prompts}
    )

    return {
        "file": str(jsonl_path),
        "project": derive_project_name(meta),
        "session_id": meta.get("id") or jsonl_path.stem,
        "parent_session_id": get_parent_session_id(meta),
        "is_subagent": is_subagent_session(meta),
        "subagent_label": get_subagent_label(meta) if is_subagent_session(meta) else None,
        "agent_role": meta.get("agent_role"),
        "originator": meta.get("originator"),
        "source": meta.get("source"),
        "source_kind": normalize_source(meta.get("source")),
        "cwd": meta.get("cwd"),
        "workspace_kind": classify_workspace(meta.get("cwd")),
        "timestamp_start": meta.get("timestamp") or first.get("timestamp"),
        "usage": usage_total,
        "total_tokens": usage_total["total_tokens"],
        "input_output_ratio": compute_input_output_ratio({"usage": usage_total, "prompts": prompts}),
        "cached_input_to_output_ratio": cached_input_to_output_ratio,
        "cached_output_ratio": cached_input_to_output_ratio,
        "prompt_count": len(prompts),
        "turn_count": turn_count,
        "base_instruction_chars": base_instruction_chars,
        "max_user_instruction_chars": max_user_instruction_chars,
        "instruction_chars": instruction_chars,
        "instruction_token_estimate": estimate_instruction_tokens(instruction_chars),
        "prompts": prompts,
        "final_message": final_message,
    }


def analyze_all() -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
]:
    """Analyze all Codex sessions."""
    projects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sessions_by_id: dict[str, dict[str, Any]] = {}
    cutoff = get_cutoff()

    for jsonl_file in iter_session_files():
        session = parse_session(jsonl_file)
        if not session:
            continue
        if session["total_tokens"] <= 0:
            continue
        if not session_in_range(session, cutoff):
            continue
        projects[session["project"]].append(session)
        sessions_by_id[session["session_id"]] = session

    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sessions in projects.values():
        for session in sessions:
            parent_id = session.get("parent_session_id")
            if parent_id:
                children_by_parent[parent_id].append(session)

    return projects, children_by_parent, sessions_by_id


def summarize_projects(
    projects: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    summaries = []
    for project_name, sessions in projects.items():
        total = defaultdict(int)
        subagent_tokens = 0
        subagent_count = 0

        for session in sessions:
            for key, value in session["usage"].items():
                total[key] += value
            if session["is_subagent"]:
                subagent_tokens += session["total_tokens"]
                subagent_count += 1

        summaries.append(
            {
                "project": project_name,
                "sessions": len(sessions),
                "usage": dict(total),
                "total_tokens": total["total_tokens"],
                "subagent_tokens": subagent_tokens,
                "subagent_count": subagent_count,
            }
        )

    summaries.sort(key=lambda item: item["total_tokens"], reverse=True)
    return summaries


def find_costly_sessions(
    projects: dict[str, list[dict[str, Any]]], top_n: int = 20
) -> list[tuple[str, dict[str, Any]]]:
    all_sessions = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if not session["is_subagent"]:
                all_sessions.append((project_name, session))

    all_sessions.sort(key=lambda item: item[1]["total_tokens"], reverse=True)
    return all_sessions[:top_n]


def find_costly_subagents(
    projects: dict[str, list[dict[str, Any]]], top_n: int = 20
) -> list[tuple[str, dict[str, Any]]]:
    all_subagents = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if session["is_subagent"]:
                all_subagents.append((project_name, session))

    all_subagents.sort(key=lambda item: item[1]["total_tokens"], reverse=True)
    return all_subagents[:top_n]


def flatten_sessions(projects: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    all_sessions = []
    for sessions in projects.values():
        all_sessions.extend(sessions)
    return all_sessions


def compute_descendant_subagent_stats(
    session_id: str, children_by_parent: dict[str, list[dict[str, Any]]]
) -> tuple[int, int]:
    total_tokens = 0
    total_count = 0
    stack = list(children_by_parent.get(session_id, []))
    visited: set[str] = set()

    while stack:
        child = stack.pop()
        child_id = child.get("session_id")
        if child_id in visited:
            continue
        if isinstance(child_id, str) and child_id:
            visited.add(child_id)
        if child["is_subagent"]:
            total_count += 1
            total_tokens += child["total_tokens"]
        stack.extend(children_by_parent.get(child["session_id"], []))

    return total_count, total_tokens


def build_group_breakdown(
    sessions: list[dict[str, Any]], key_name: str
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = defaultdict(
        lambda: {"sessions": 0, "total_tokens": 0, "subagent_sessions": 0}
    )

    for session in sessions:
        key = session.get(key_name) or "unknown"
        grouped[key]["sessions"] += 1
        grouped[key]["total_tokens"] += session["total_tokens"]
        if session["is_subagent"]:
            grouped[key]["subagent_sessions"] += 1

    rows = []
    for key, values in grouped.items():
        rows.append({"name": key, **values})

    rows.sort(key=lambda row: row["total_tokens"], reverse=True)
    return rows


def find_input_output_ratio_outliers(
    projects: dict[str, list[dict[str, Any]]], top_n: int = 15
) -> list[tuple[str, dict[str, Any]]]:
    candidates = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if session["is_subagent"]:
                continue
            if session["usage"].get("output_tokens", 0) <= 0:
                continue
            if session["total_tokens"] < 1_000_000:
                continue
            ratio = session.get("input_output_ratio")
            if ratio is not None:
                candidates.append((project_name, session))

    candidates.sort(
        key=lambda item: (
            item[1]["input_output_ratio"],
            item[1]["total_tokens"],
        ),
        reverse=True,
    )
    return candidates[:top_n]


def find_instruction_heavy_sessions(
    projects: dict[str, list[dict[str, Any]]], top_n: int = 15
) -> list[tuple[str, dict[str, Any]]]:
    candidates = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if session["is_subagent"]:
                continue
            if session["instruction_chars"] <= 0:
                continue
            candidates.append((project_name, session))

    candidates.sort(
        key=lambda item: (
            item[1]["instruction_chars"],
            item[1]["total_tokens"],
        ),
        reverse=True,
    )
    return candidates[:top_n]


def find_subagent_overhead_outliers(
    projects: dict[str, list[dict[str, Any]]],
    children_by_parent: dict[str, list[dict[str, Any]]],
    top_n: int = 15,
) -> list[tuple[str, dict[str, Any], int, int]]:
    candidates = []
    for project_name, sessions in projects.items():
        for session in sessions:
            if session["is_subagent"]:
                continue
            descendant_count, descendant_tokens = compute_descendant_subagent_stats(
                session["session_id"], children_by_parent
            )
            if descendant_count <= 0:
                continue
            candidates.append((project_name, session, descendant_count, descendant_tokens))

    candidates.sort(key=lambda item: item[3], reverse=True)
    return candidates[:top_n]


def write_report(
    projects: dict[str, list[dict[str, Any]]],
    summaries: list[dict[str, Any]],
    children_by_parent: dict[str, list[dict[str, Any]]],
    sessions_by_id: dict[str, dict[str, Any]],
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / "token_report.md"

    cutoff = get_cutoff()
    date_range = format_date_range(cutoff)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    grand_input = sum(s["usage"].get("input_tokens", 0) for s in summaries)
    grand_cached = sum(s["usage"].get("cached_input_tokens", 0) for s in summaries)
    grand_output = sum(s["usage"].get("output_tokens", 0) for s in summaries)
    grand_reasoning = sum(s["usage"].get("reasoning_output_tokens", 0) for s in summaries)
    grand_total = sum(s["total_tokens"] for s in summaries)
    total_sessions = sum(s["sessions"] for s in summaries)
    total_subagent_tokens = sum(s["subagent_tokens"] for s in summaries)
    total_subagent_count = sum(s["subagent_count"] for s in summaries)
    all_sessions = flatten_sessions(projects)
    orphan_subagent_count = sum(
        1
        for session in all_sessions
        if session["is_subagent"]
        and session.get("parent_session_id")
        and session["parent_session_id"] not in sessions_by_id
    )
    originator_rows = build_group_breakdown(all_sessions, "originator")
    role_rows = build_group_breakdown(all_sessions, "agent_role")
    workspace_rows = build_group_breakdown(all_sessions, "workspace_kind")

    lines = [
        tr("report_title"),
        "",
        tr("report_generated", now=now, date_range=date_range),
        "",
        tr("report_grand_totals"),
        "",
        tr("report_projects", count=len(summaries)),
        tr("report_sessions", count=f"{total_sessions:,}"),
        tr("report_total_tokens", value=format_tokens(grand_total)),
        tr("report_input", value=format_tokens(grand_input)),
        tr("report_cached_input", value=format_tokens(grand_cached)),
        tr("report_output", value=format_tokens(grand_output)),
        tr("report_reasoning_output", value=format_tokens(grand_reasoning)),
        tr(
            "report_subagent_sessions",
            count=f"{total_subagent_count:,}",
            tokens=format_tokens(total_subagent_tokens),
        ),
        tr(
            "report_subagents_missing_parent",
            count=f"{orphan_subagent_count:,}",
        ),
        "",
        tr("report_by_project"),
        "",
        f"| {tr('table_project')} | {tr('table_sessions')} | {tr('col_total')} | {tr('col_input')} | {tr('col_cached_input')} | {tr('col_output')} | {tr('col_reasoning')} | {tr('table_subagents')} |",
        "|---------|----------|-------|-------|--------------|--------|-----------|-----------|",
    ]

    for summary in summaries:
        usage = summary["usage"]
        lines.append(
            f"| {format_table_cell(summary['project'])} | {summary['sessions']} "
            f"| {format_tokens(summary['total_tokens'])} "
            f"| {format_tokens(usage.get('input_tokens', 0))} "
            f"| {format_tokens(usage.get('cached_input_tokens', 0))} "
            f"| {format_tokens(usage.get('output_tokens', 0))} "
            f"| {format_tokens(usage.get('reasoning_output_tokens', 0))} "
            f"| {summary['subagent_count']} ({format_tokens(summary['subagent_tokens'])}) |"
        )

    lines.extend(["", tr("report_most_costly_sessions"), ""])

    for index, (project_name, session) in enumerate(find_costly_sessions(projects, top_n=25), 1):
        project_label = format_table_cell(project_name, limit=80)
        lines.append(
            tr(
                "report_session_title",
                index=index,
                project=project_label,
                tokens=format_tokens(session["total_tokens"]),
            )
        )
        lines.append(tr("report_session_label", session_id=session["session_id"]))
        if session.get("timestamp_start"):
            lines.append(
                tr(
                    "report_started_label",
                    value=session["timestamp_start"][:19].replace("T", " "),
                )
            )
        if session.get("cwd"):
            lines.append(tr("report_cwd_label", value=session["cwd"]))
        child_count = len(children_by_parent.get(session["session_id"], []))
        lines.append(tr("report_direct_subagents_label", count=child_count))

        usage = session["usage"]
        lines.append(
            tr(
                "report_tokens_label",
                input=format_tokens(usage.get("input_tokens", 0)),
                cached_input=format_tokens(usage.get("cached_input_tokens", 0)),
                output=format_tokens(usage.get("output_tokens", 0)),
                reasoning=format_tokens(usage.get("reasoning_output_tokens", 0)),
            )
        )

        if session["prompts"]:
            first_prompt = get_first_prompt_text(session, limit=400)
            lines.append(tr("report_first_prompt_label"))
            lines.append(f"  > {first_prompt}")
        lines.append("")

    lines.extend(
        [
            tr("report_highest_ratios"),
            "",
            f"| # | {tr('table_project')} | {tr('col_session')} | Input/Output | Cached/Output | {tr('table_total_tokens')} | {tr('col_first_prompt')} |",
            "|---|---------|---------|--------------|---------------|--------------|--------------|",
        ]
    )

    for index, (project_name, session) in enumerate(
        find_input_output_ratio_outliers(projects), 1
    ):
        lines.append(
            f"| {index} | {format_table_cell(project_name, limit=80)} | `{short_session_id(session['session_id'])}` "
            f"| {format_ratio(session.get('input_output_ratio'))} "
            f"| {format_ratio(get_cached_input_to_output_ratio(session))} "
            f"| {format_tokens(session['total_tokens'])} "
            f"| {format_table_cell(get_first_prompt_text(session, limit=90))} |"
        )

    lines.extend(
        [
            "",
            tr("report_subagent_overhead_hotspots"),
            "",
            f"| # | {tr('table_project')} | {tr('col_parent_session')} | {tr('col_descendant_subagents')} | {tr('col_descendant_tokens')} | {tr('col_overhead_vs_parent')} | {tr('col_parent_tokens')} | {tr('col_first_prompt')} |",
            "|---|---------|----------------|---------------------|-------------------|------------------|---------------|--------------|",
        ]
    )

    for index, (project_name, session, descendant_count, descendant_tokens) in enumerate(
        find_subagent_overhead_outliers(projects, children_by_parent), 1
    ):
        overhead_ratio = descendant_tokens / max(session["total_tokens"], 1)
        lines.append(
            f"| {index} | {format_table_cell(project_name, limit=80)} | `{short_session_id(session['session_id'])}` "
            f"| {descendant_count} "
            f"| {format_tokens(descendant_tokens)} "
            f"| {format_percent(overhead_ratio * 100)} "
            f"| {format_tokens(session['total_tokens'])} "
            f"| {format_table_cell(get_first_prompt_text(session, limit=90))} |"
        )

    lines.extend(
        [
            "",
            tr("report_most_costly_subagents"),
            "",
            f"| # | {tr('table_project')} | {tr('col_parent_session')} | {tr('col_subagent')} | {tr('col_role')} | {tr('table_total_tokens')} | {tr('col_input')} | {tr('col_cached_input')} | {tr('col_output')} |",
            "|---|---------|----------------|----------|------|--------------|-------|--------------|--------|",
        ]
    )

    for index, (project_name, session) in enumerate(find_costly_subagents(projects, top_n=20), 1):
        usage = session["usage"]
        parent_label = short_session_id(session.get("parent_session_id"))
        subagent_label = format_table_cell(session.get("subagent_label") or "?", limit=48)
        role_label = format_table_cell(session.get("agent_role") or "?", limit=48)
        lines.append(
            f"| {index} | {format_table_cell(project_name, limit=80)} | `{parent_label}` "
            f"| {subagent_label} "
            f"| {role_label} "
            f"| {format_tokens(session['total_tokens'])} "
            f"| {format_tokens(usage.get('input_tokens', 0))} "
            f"| {format_tokens(usage.get('cached_input_tokens', 0))} "
            f"| {format_tokens(usage.get('output_tokens', 0))} |"
        )

    lines.extend(["", tr("report_subagent_usage_by_project"), ""])
    lines.append(f"| {tr('table_project')} | {tr('col_subagent_sessions')} | {tr('col_subagent_tokens')} |")
    lines.append("|---------|-------------------|-----------------|")

    project_subagent_stats = []
    for project_name, sessions in projects.items():
        subagent_count = sum(1 for session in sessions if session["is_subagent"])
        subagent_tokens = sum(
            session["total_tokens"] for session in sessions if session["is_subagent"]
        )
        if subagent_count:
            project_subagent_stats.append((project_name, subagent_count, subagent_tokens))

    project_subagent_stats.sort(key=lambda item: item[2], reverse=True)
    for project_name, count, tokens in project_subagent_stats:
        lines.append(f"| {format_table_cell(project_name)} | {count} | {format_tokens(tokens)} |")

    lines.extend(
        [
            "",
            tr("report_usage_by_originator"),
            "",
            f"| {tr('col_originator')} | {tr('table_sessions')} | {tr('table_total_tokens')} | {tr('col_subagent_sessions')} |",
            "|------------|----------|--------------|-------------------|",
        ]
    )

    for row in originator_rows:
        lines.append(
            f"| {format_table_cell(row['name'])} | {row['sessions']} | {format_tokens(row['total_tokens'])} | {row['subagent_sessions']} |"
        )

    lines.extend(
        [
            "",
            tr("report_usage_by_agent_role"),
            "",
            f"| {tr('col_agent_role')} | {tr('table_sessions')} | {tr('table_total_tokens')} | {tr('col_subagent_sessions')} |",
            "|------------|----------|--------------|-------------------|",
        ]
    )

    for row in role_rows:
        lines.append(
            f"| {format_table_cell(row['name'])} | {row['sessions']} | {format_tokens(row['total_tokens'])} | {row['subagent_sessions']} |"
        )

    lines.extend(
        [
            "",
            tr("report_usage_by_workspace_kind"),
            "",
            f"| {tr('col_workspace_kind')} | {tr('table_sessions')} | {tr('table_total_tokens')} | {tr('col_subagent_sessions')} |",
            "|----------------|----------|--------------|-------------------|",
        ]
    )

    for row in workspace_rows:
        lines.append(
            f"| {format_table_cell(row['name'])} | {row['sessions']} | {format_tokens(row['total_tokens'])} | {row['subagent_sessions']} |"
        )

    lines.extend(
        [
            "",
            tr("report_instruction_heavy"),
            "",
            f"| # | {tr('table_project')} | {tr('col_session')} | {tr('col_base_instr_chars')} | {tr('col_max_turn_instr_chars')} | {tr('col_combined_chars')} | {tr('col_est_tokens')} | {tr('col_first_prompt')} |",
            "|---|---------|---------|------------------|----------------------|----------------|-------------|--------------|",
        ]
    )

    for index, (project_name, session) in enumerate(
        find_instruction_heavy_sessions(projects), 1
    ):
        lines.append(
            f"| {index} | {format_table_cell(project_name, limit=80)} | `{short_session_id(session['session_id'])}` "
            f"| {format_tokens(session['base_instruction_chars'])} "
            f"| {format_tokens(session['max_user_instruction_chars'])} "
            f"| {format_tokens(session['instruction_chars'])} "
            f"| ~{format_tokens(session['instruction_token_estimate'])} "
            f"| {format_table_cell(get_first_prompt_text(session, limit=90))} |"
        )

    lines.extend(["", tr("report_likely_savings"), ""])

    top_non_subagent_sessions = find_costly_sessions(projects, top_n=5)
    top_non_subagent_total = sum(session["total_tokens"] for _, session in top_non_subagent_sessions)
    top_non_subagent_share = top_non_subagent_total / max(grand_total, 1)

    if total_subagent_tokens > 0:
        share = total_subagent_tokens / max(grand_total, 1)
        lines.append(
            tr(
                "insight_subagent_cost",
                subagent_tokens=format_tokens(total_subagent_tokens),
                grand_total=format_tokens(grand_total),
                share=format_percent(share * 100),
            )
        )

    if grand_output > 0:
        cached_output_ratio = grand_cached / grand_output
        input_output_ratio = grand_input / grand_output
        lines.append(
            tr(
                "insight_context_replay",
                input_output_ratio=format_ratio(input_output_ratio),
                cached_output_ratio=format_ratio(cached_output_ratio),
            )
        )

    if top_non_subagent_sessions:
        lines.append(
            tr(
                "insight_top_sessions_share",
                tokens=format_tokens(top_non_subagent_total),
                share=format_percent(top_non_subagent_share * 100),
            )
        )

    hottest_overhead = find_subagent_overhead_outliers(projects, children_by_parent, top_n=1)
    if hottest_overhead:
        project_name, parent_session, descendant_count, descendant_tokens = hottest_overhead[0]
        overhead_ratio = descendant_tokens / max(parent_session["total_tokens"], 1)
        lines.append(
            tr(
                "insight_hotspot",
                session_id=parent_session["session_id"],
                project=project_name,
                descendant_count=descendant_count,
                descendant_tokens=format_tokens(descendant_tokens),
                overhead_ratio=format_percent(overhead_ratio * 100),
            )
        )

    heaviest_instruction_sessions = find_instruction_heavy_sessions(projects, top_n=1)
    if heaviest_instruction_sessions:
        project_name, session = heaviest_instruction_sessions[0]
        lines.append(
            tr(
                "insight_instruction_heavy",
                session_id=session["session_id"],
                project=project_name,
                instruction_chars=format_tokens(session["instruction_chars"]),
                instruction_tokens=format_tokens(session["instruction_token_estimate"]),
            )
        )

    report_path.write_text("\n".join(lines) + "\n")
    return report_path


def build_json_report(
    projects: dict[str, list[dict[str, Any]]],
    summaries: list[dict[str, Any]],
    children_by_parent: dict[str, list[dict[str, Any]]],
    sessions_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cutoff = get_cutoff()
    all_sessions = flatten_sessions(projects)

    grand_input = sum(s["usage"].get("input_tokens", 0) for s in summaries)
    grand_cached = sum(s["usage"].get("cached_input_tokens", 0) for s in summaries)
    grand_output = sum(s["usage"].get("output_tokens", 0) for s in summaries)
    grand_reasoning = sum(s["usage"].get("reasoning_output_tokens", 0) for s in summaries)
    grand_total = sum(s["total_tokens"] for s in summaries)
    total_sessions = sum(s["sessions"] for s in summaries)
    total_subagent_tokens = sum(s["subagent_tokens"] for s in summaries)
    total_subagent_count = sum(s["subagent_count"] for s in summaries)
    orphan_subagent_count = sum(
        1
        for session in all_sessions
        if session["is_subagent"]
        and session.get("parent_session_id")
        and session["parent_session_id"] not in sessions_by_id
    )

    top_sessions = []
    for project_name, session in find_costly_sessions(projects, top_n=25):
        top_sessions.append(
            {
                "project": project_name,
                "session_id": session["session_id"],
                "timestamp_start": session.get("timestamp_start"),
                "cwd": session.get("cwd"),
                "total_tokens": session["total_tokens"],
                "usage": session["usage"],
                "prompt_count": session.get("prompt_count", 0),
                "turn_count": session.get("turn_count", 0),
                "input_output_ratio": session.get("input_output_ratio"),
                "cached_input_to_output_ratio": get_cached_input_to_output_ratio(session),
                "cached_output_ratio": session.get("cached_output_ratio"),
                "first_prompt": get_first_prompt_text(session, limit=240),
            }
        )

    top_subagents = []
    for project_name, session in find_costly_subagents(projects, top_n=25):
        top_subagents.append(
            {
                "project": project_name,
                "session_id": session["session_id"],
                "parent_session_id": session.get("parent_session_id"),
                "subagent_label": session.get("subagent_label"),
                "agent_role": session.get("agent_role"),
                "total_tokens": session["total_tokens"],
                "usage": session["usage"],
            }
        )

    input_output_outliers = []
    for project_name, session in find_input_output_ratio_outliers(projects, top_n=25):
        input_output_outliers.append(
            {
                "project": project_name,
                "session_id": session["session_id"],
                "input_output_ratio": session.get("input_output_ratio"),
                "cached_input_to_output_ratio": get_cached_input_to_output_ratio(session),
                "cached_output_ratio": session.get("cached_output_ratio"),
                "total_tokens": session["total_tokens"],
                "first_prompt": get_first_prompt_text(session, limit=200),
            }
        )

    subagent_overhead = []
    for project_name, session, descendant_count, descendant_tokens in find_subagent_overhead_outliers(
        projects, children_by_parent, top_n=25
    ):
        parent_total = max(session["total_tokens"], 1)
        subagent_overhead.append(
            {
                "project": project_name,
                "parent_session_id": session["session_id"],
                "descendant_subagents": descendant_count,
                "descendant_tokens": descendant_tokens,
                "overhead_vs_parent_percent": round((descendant_tokens / parent_total) * 100, 2),
                "parent_tokens": session["total_tokens"],
                "first_prompt": get_first_prompt_text(session, limit=200),
            }
        )

    instruction_heavy = []
    for project_name, session in find_instruction_heavy_sessions(projects, top_n=25):
        instruction_heavy.append(
            {
                "project": project_name,
                "session_id": session["session_id"],
                "base_instruction_chars": session["base_instruction_chars"],
                "max_user_instruction_chars": session["max_user_instruction_chars"],
                "instruction_chars": session["instruction_chars"],
                "instruction_token_estimate": session["instruction_token_estimate"],
                "first_prompt": get_first_prompt_text(session, limit=200),
            }
        )

    return {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "range": f"since {cutoff.date().isoformat()}" if cutoff else "all_time",
            "filters": {
                "since_days": SINCE_DAYS,
                "since_date": SINCE_DATE,
                "redact_prompts": REDACT_PROMPTS,
                "report_lang": REPORT_LANG,
            },
            "paths": {
                "codex_home": str(CODEX_HOME),
                "output_dir": str(OUTPUT_DIR),
                "session_dirs": [str(p) for p in SESSION_DIRS],
            },
        },
        "totals": {
            "projects": len(summaries),
            "sessions": total_sessions,
            "total_tokens": grand_total,
            "input_tokens": grand_input,
            "cached_input_tokens": grand_cached,
            "output_tokens": grand_output,
            "reasoning_output_tokens": grand_reasoning,
            "subagent_sessions": total_subagent_count,
            "subagent_tokens": total_subagent_tokens,
            "subagents_with_missing_parent_in_range": orphan_subagent_count,
        },
        "project_summaries": summaries,
        "breakdowns": {
            "originator": build_group_breakdown(all_sessions, "originator"),
            "agent_role": build_group_breakdown(all_sessions, "agent_role"),
            "workspace_kind": build_group_breakdown(all_sessions, "workspace_kind"),
        },
        "top_costly_sessions": top_sessions,
        "top_costly_subagents": top_subagents,
        "input_output_ratio_outliers": input_output_outliers,
        "subagent_overhead_hotspots": subagent_overhead,
        "instruction_heavy_sessions": instruction_heavy,
    }


def write_json_report(report_data: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "token_report.json"
    json_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2) + "\n")
    return json_path


def write_prompts_by_project(projects: dict[str, list[dict[str, Any]]]) -> Path:
    prompts_dir = OUTPUT_DIR / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    for project_name, sessions in projects.items():
        all_prompts = []
        for session in sessions:
            if session["is_subagent"]:
                continue
            for prompt in session["prompts"]:
                all_prompts.append(
                    {
                        "session_id": session["session_id"],
                        "timestamp": prompt.get("timestamp", ""),
                        "text": prompt["text"],
                    }
                )

        if not all_prompts:
            continue

        all_prompts.sort(key=lambda item: item["timestamp"] or "")
        safe_name = make_safe_filename(project_name)
        out_path = prompts_dir / f"{safe_name}.md"

        lines = [
            tr("prompts_title", project=project_name),
            "",
            tr(
                "prompts_summary",
                prompt_count=len(all_prompts),
                session_count=len(sessions),
            ),
            "",
        ]

        for index, prompt in enumerate(all_prompts, 1):
            timestamp = (
                prompt["timestamp"][:19].replace("T", " ")
                if prompt["timestamp"]
                else tr("unknown")
            )
            lines.append(
                tr(
                    "prompts_session_item",
                    index=index,
                    timestamp=timestamp,
                    session_id=prompt["session_id"][:8],
                )
            )
            lines.append("")
            if REDACT_PROMPTS:
                lines.append(redact_prompt_text(prompt["text"]))
            else:
                lines.append(prompt["text"])
            lines.append("")

        out_path.write_text("\n".join(lines))

    return prompts_dir


def print_summary(
    summaries: list[dict[str, Any]], projects: dict[str, list[dict[str, Any]]]
) -> None:
    grand_total = sum(summary["total_tokens"] for summary in summaries)
    total_sessions = sum(summary["sessions"] for summary in summaries)
    terminal_columns = get_terminal_columns()
    max_project_name = max(
        (len(sanitize_text(summary["project"])) for summary in summaries), default=32
    )
    max_project_width_for_terminal = max(24, terminal_columns - 35)
    project_width = max(24, min(52, max_project_name, max_project_width_for_terminal))

    print(
        "\n"
        + tr(
            "console_total_summary",
            tokens=format_tokens(grand_total),
            sessions=total_sessions,
            projects=len(summaries),
        )
        + "\n"
    )
    print(
        f"{tr('table_project'):<{project_width}} {tr('table_sessions'):>8} "
        f"{tr('table_total_tokens'):>14} {tr('table_subagents'):>10}"
    )
    print("-" * (project_width + 35))

    for summary in summaries[:30]:
        project_label = truncate_text(sanitize_text(summary["project"]), project_width)
        print(
            f"{project_label:<{project_width}} {summary['sessions']:>8,} "
            f"{format_tokens(summary['total_tokens']):>14} {summary['subagent_count']:>10,}"
        )

    print(f"\n{tr('console_top_10')}")
    for project_name, session in find_costly_sessions(projects, top_n=10):
        started = session["timestamp_start"][:10] if session["timestamp_start"] else "?"
        first_prompt = tr("console_no_prompt")
        if session["prompts"]:
            first_prompt = get_first_prompt_text(session, limit=max(50, terminal_columns - 12))
        prompt_width = max(50, terminal_columns - 12)
        print(
            f"  [{started}] {project_name}: {format_tokens(session['total_tokens'])}"
        )
        print(f"      {truncate_text(first_prompt, prompt_width)}")
        print("")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        configure_runtime(args)
    except ValueError as exc:
        print(f"{tr('error_prefix')}: {exc}", file=sys.stderr)
        return 2

    print(tr("console_scanning"))
    projects, children_by_parent, sessions_by_id = analyze_all()
    summaries = summarize_projects(projects)

    print(tr("console_found_projects", count=len(projects)))
    print_summary(summaries, projects)

    report_path = write_report(projects, summaries, children_by_parent, sessions_by_id)
    json_path = None
    if WRITE_JSON:
        report_data = build_json_report(projects, summaries, children_by_parent, sessions_by_id)
        json_path = write_json_report(report_data)
    prompts_dir = write_prompts_by_project(projects)

    print("\n" + tr("console_full_report", path=report_path))
    if json_path:
        print(tr("console_json_report", path=json_path))
    print(tr("console_prompts", path=prompts_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
