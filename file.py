"""
agente_schema.py
Lê um schema.md (no padrão Schema.md) + um arquivo Excel e gera uma
versão tratada/validada do Excel de acordo com as regras do schema.

Uso:
    python agente_schema.py --excel dados.xlsx --schema schema.md --saida dados_tratado.xlsx

Dependências:
    pip install pandas openpyxl python-dateutil
"""

import argparse
import re
import uuid
from datetime import datetime, date
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------
# 1. Mapeamento manual: nome da aba no Excel -> nome da tabela no schema.md
#    Edite aqui se os nomes não forem idênticos (ex.: "Tarefas" -> "tasks")
# --------------------------------------------------------------------------
SHEET_TABLE_MAP = {
    # "NomeDaAba": "nome_da_tabela",
}

# Palavras-chave de coluna que disparam normalizações específicas
EMAIL_HINTS = ("email",)
SLUG_HINTS = ("slug",)
UUID_HINTS = ("_id", "id")
DATE_HINTS = ("_at", "date", "_date")
BOOL_TRUE = {"true", "1", "sim", "yes", "y", "verdadeiro"}
BOOL_FALSE = {"false", "0", "não", "nao", "no", "n", "falso"}


# --------------------------------------------------------------------------
# 2. Parser do schema.md
# --------------------------------------------------------------------------
def split_top_level(text, sep=","):
    """Divide uma string por vírgulas, ignorando vírgulas dentro de parênteses."""
    parts, depth, current = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def parse_create_table_block(sql_block):
    """Extrai nome da tabela e specs de colunas de um bloco CREATE TABLE."""
    match = re.search(r"CREATE TABLE\s+`?(\w+)`?\s*\((.*)\)\s*;", sql_block, re.DOTALL | re.IGNORECASE)
    if not match:
        return None, {}

    table_name = match.group(1).lower()
    body = match.group(2)
    lines = split_top_level(body)

    columns = {}
    for line in lines:
        line = line.strip().rstrip(",")
        if not line:
            continue

        # Constraints nomeadas (CONSTRAINT ... CHECK / UNIQUE) aplicadas depois
        constraint_check = re.match(
            r"CONSTRAINT\s+\w+\s+CHECK\s*\(\s*(\w+)\s+IN\s*\((.*?)\)\s*\)", line, re.IGNORECASE
        )
        if constraint_check:
            col, values_raw = constraint_check.groups()
            values = [v.strip().strip("'\"") for v in values_raw.split(",")]
            columns.setdefault(col.lower(), {}).setdefault("allowed_values", values)
            continue

        # Ignora outras constraints de linha inteira (PRIMARY KEY(...), FOREIGN KEY(...), UNIQUE(...), INDEX)
        if re.match(r"(PRIMARY KEY|FOREIGN KEY|UNIQUE\s*\(|INDEX|KEY\s)", line, re.IGNORECASE):
            continue

        tokens = line.split(None, 1)
        if len(tokens) < 2:
            continue
        col_name, rest = tokens[0].strip("`"), tokens[1]
        col_name = col_name.lower()

        col_type_match = re.match(r"[\w()]+(\[\])?", rest)
        col_type = col_type_match.group(0) if col_type_match else "TEXT"

        nullable = "NOT NULL" not in rest.upper()
        default_match = re.search(r"DEFAULT\s+([^\s,]+(\(\))?)", rest, re.IGNORECASE)
        default_val = default_match.group(1) if default_match else None

        check_match = re.search(r"CHECK\s*\(\s*\w+\s+IN\s*\((.*?)\)\s*\)", rest, re.IGNORECASE)
        allowed_values = None
        if check_match:
            allowed_values = [v.strip().strip("'\"") for v in check_match.group(1).split(",")]

        is_pk = "PRIMARY KEY" in rest.upper()
        is_unique = "UNIQUE" in rest.upper()

        fk_match = re.search(r"REFERENCES\s+(\w+)\s*\((\w+)\)", rest, re.IGNORECASE)
        fk = fk_match.groups() if fk_match else None

        columns[col_name] = {
            "type": col_type.upper(),
            "nullable": nullable,
            "default": default_val,
            "allowed_values": allowed_values,
            "is_pk": is_pk,
            "is_unique": is_unique,
            "fk": fk,
            "description": None,
        }

    return table_name, columns


def parse_markdown_column_table(md_table_text):
    """Extrai dados de uma tabela markdown '| Column | Type | Nullable | Default | Description |'."""
    rows = [r.strip() for r in md_table_text.strip().splitlines() if r.strip().startswith("|")]
    if len(rows) < 2:
        return {}
    header = [h.strip().lower() for h in rows[0].strip("|").split("|")]
    if "column" not in header:
        return {}

    idx = {name: i for i, name in enumerate(header)}
    result = {}
    for row in rows[2:]:  # pula header e linha separadora
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < len(header):
            continue
        col = cells[idx["column"]].strip("` ").lower()
        if not col:
            continue
        entry = {}
        if "type" in idx:
            entry["type"] = cells[idx["type"]]
        if "nullable" in idx:
            entry["nullable"] = cells[idx["nullable"]].strip().lower().startswith("y") or cells[idx["nullable"]].strip().lower() == "sim"
        if "default" in idx:
            d = cells[idx["default"]].strip()
            entry["default"] = None if d in ("-", "") else d
        if "description" in idx:
            entry["description"] = cells[idx["description"]]
        result[col] = entry
    return result


def parse_schema_md(schema_path):
    """Retorna dict: { nome_tabela: {"columns": {...}, "business_rules": [...]} }"""
    text = Path(schema_path).read_text(encoding="utf-8")

    tables = {}
    current_table = None

    # 1) Heading que parece nome de tabela (ex.: "#### organizations")
    heading_pattern = re.compile(r"^#{2,4}\s+`?(\w+)`?\s*$", re.MULTILINE)

    # 2) Blocos de código ```sql ... ```
    sql_blocks = list(re.finditer(r"```sql\s*(.*?)```", text, re.DOTALL))

    # 3) Tabelas markdown de coluna (com header contendo "Column" e "Type")
    md_table_blocks = list(re.finditer(r"(\|\s*Column\s*\|.*?\n)((?:\|.*\n?)+)", text, re.IGNORECASE))

    # Percorre o documento linearmente para associar cada elemento ao heading/tabela mais próxima
    events = []
    for h in heading_pattern.finditer(text):
        events.append((h.start(), "heading", h.group(1).lower()))
    for b in sql_blocks:
        if "CREATE TABLE" in b.group(1).upper():
            events.append((b.start(), "sql", b.group(1)))
    for m in md_table_blocks:
        events.append((m.start(), "mdtable", m.group(1) + m.group(2)))
    # Regras de negócio: bullets logo após "**Business Rules**:"
    for br in re.finditer(r"\*\*Business Rules\*\*:?\s*\n((?:\s*-\s+.*\n?)+)", text):
        events.append((br.start(), "rules", br.group(1)))

    events.sort(key=lambda e: e[0])

    for _, kind, payload in events:
        if kind == "heading":
            current_table = payload
        elif kind == "sql":
            name, cols = parse_create_table_block("CREATE TABLE " + payload.split("CREATE TABLE", 1)[1])
            if name:
                current_table = name
                tables.setdefault(name, {"columns": {}, "business_rules": []})
                for c, spec in cols.items():
                    tables[name]["columns"].setdefault(c, {}).update(spec)
        elif kind == "mdtable" and current_table:
            col_info = parse_markdown_column_table(payload)
            tables.setdefault(current_table, {"columns": {}, "business_rules": []})
            for c, spec in col_info.items():
                tables[current_table]["columns"].setdefault(c, {}).update(
                    {k: v for k, v in spec.items() if v is not None}
                )
        elif kind == "rules" and current_table:
            rules = [ln.strip("- ").strip() for ln in payload.strip().splitlines()]
            tables.setdefault(current_table, {"columns": {}, "business_rules": []})
            tables[current_table]["business_rules"].extend(rules)

    return tables


# --------------------------------------------------------------------------
# 3. Normalização / validação de valores
# --------------------------------------------------------------------------
def resolve_sql_default(default_raw, col_name):
    """Converte defaults do SQL (gen_random_uuid(), CURRENT_TIMESTAMP...) em valores reais."""
    if default_raw is None:
        return None
    d = default_raw.strip().strip("'\"")
    upper = d.upper()
    if "GEN_RANDOM_UUID" in upper or "NEWID" in upper or "UUID" in upper:
        return lambda: str(uuid.uuid4())
    if upper in ("CURRENT_TIMESTAMP", "NOW()", "GETUTCDATE()"):
        return lambda: datetime.utcnow().isoformat()
    if upper in ("TRUE", "FALSE"):
        return upper == "TRUE"
    try:
        return int(d)
    except ValueError:
        pass
    try:
        return float(d)
    except ValueError:
        pass
    return d  # valor literal (ex.: 'draft', 'member')


def is_empty(value):
    return value is None or (isinstance(value, float) and pd.isna(value)) or (isinstance(value, str) and value.strip() == "")


def normalize_email(value):
    return value.strip().lower()


def slugify(value):
    s = value.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def coerce_type(value, col_type):
    """Tenta converter o valor para o tipo declarado no schema. Retorna (valor, erro_ou_None)."""
    if is_empty(value):
        return value, None
    t = (col_type or "").upper()
    try:
        if any(k in t for k in ("INT", "SERIAL", "BIGINT")):
            return int(float(value)), None
        if any(k in t for k in ("NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")):
            return float(value), None
        if "BOOL" in t:
            s = str(value).strip().lower()
            if s in BOOL_TRUE:
                return True, None
            if s in BOOL_FALSE:
                return False, None
            return value, f"valor booleano não reconhecido: '{value}'"
        if any(k in t for k in ("TIMESTAMP", "DATE", "DATETIME")):
            parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
            if pd.isna(parsed):
                return value, f"data/hora inválida: '{value}'"
            return parsed.isoformat(), None
        # texto: apenas trim
        if isinstance(value, str):
            return value.strip(), None
        return value, None
    except (ValueError, TypeError):
        return value, f"não foi possível converter '{value}' para o tipo {col_type}"


# --------------------------------------------------------------------------
# 4. Aplicação das regras a um DataFrame
# --------------------------------------------------------------------------
def apply_schema_to_dataframe(df, table_name, columns_spec):
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    errors = []  # cada item: dict(tabela, linha, coluna, valor, problema, acao)
    status = ["OK"] * len(df)
    obs = [""] * len(df)

    # Cria colunas ausentes que tenham default no schema
    for col, spec in columns_spec.items():
        if col not in df.columns and spec.get("default") is not None:
            resolved = resolve_sql_default(spec["default"], col)
            df[col] = [resolved() if callable(resolved) else resolved for _ in range(len(df))]
            errors.append({
                "tabela": table_name, "linha": "-", "coluna": col,
                "valor_original": None, "problema": "coluna ausente",
                "acao": f"preenchida com default '{spec['default']}'"
            })

    for col, spec in columns_spec.items():
        if col not in df.columns:
            continue

        col_type = spec.get("type", "")
        nullable = spec.get("nullable", True)
        allowed = spec.get("allowed_values")

        for i, raw_value in df[col].items():
            value = raw_value
            problem = None
            action = None

            if is_empty(value):
                if not nullable:
                    default = spec.get("default")
                    if default is not None:
                        resolved = resolve_sql_default(default, col)
                        value = resolved() if callable(resolved) else resolved
                        action = f"vazio preenchido com default '{default}'"
                    else:
                        problem = "campo obrigatório vazio (NOT NULL)"
            else:
                # Normalizações específicas por nome de coluna
                if any(h in col for h in EMAIL_HINTS) and isinstance(value, str):
                    value = normalize_email(value)
                    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
                        problem = f"e-mail em formato inválido: '{value}'"

                elif any(h in col for h in SLUG_HINTS) and isinstance(value, str):
                    fixed = slugify(value)
                    if fixed != value.strip().lower():
                        action = f"slug normalizado de '{value}' para '{fixed}'"
                    value = fixed

                else:
                    value, type_err = coerce_type(value, col_type)
                    if type_err:
                        problem = type_err

                # Validação de domínio (CHECK ... IN (...))
                if allowed and problem is None:
                    if str(value) not in allowed:
                        # tenta correção por normalização simples
                        normalized_match = next(
                            (a for a in allowed if str(value).strip().lower() == a.strip().lower()), None
                        )
                        if normalized_match:
                            action = f"valor '{value}' normalizado para '{normalized_match}'"
                            value = normalized_match
                        else:
                            problem = f"valor '{value}' fora do domínio permitido {allowed}"

            df.at[i, col] = value
            if problem:
                status[i] = "ERRO"
                obs[i] = (obs[i] + " | " if obs[i] else "") + problem
                errors.append({
                    "tabela": table_name, "linha": i + 2, "coluna": col,
                    "valor_original": raw_value, "problema": problem, "acao": "revisar manualmente"
                })
            elif action:
                if status[i] == "OK":
                    status[i] = "CORRIGIDO"
                obs[i] = (obs[i] + " | " if obs[i] else "") + action
                errors.append({
                    "tabela": table_name, "linha": i + 2, "coluna": col,
                    "valor_original": raw_value, "problema": "-", "acao": action
                })

    # Verifica duplicidade em colunas UNIQUE
    for col, spec in columns_spec.items():
        if spec.get("is_unique") and col in df.columns:
            dup_mask = df[col].duplicated(keep=False) & df[col].notna()
            for i in df[dup_mask].index:
                status[i] = "ERRO"
                obs[i] = (obs[i] + " | " if obs[i] else "") + f"valor duplicado em coluna única '{col}'"
                errors.append({
                    "tabela": table_name, "linha": i + 2, "coluna": col,
                    "valor_original": df.at[i, col], "problema": "valor duplicado (UNIQUE)", "acao": "revisar manualmente"
                })

    df["_status"] = status
    df["_observacoes"] = obs
    return df, errors


# --------------------------------------------------------------------------
# 5. Orquestração
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Aplica as regras de schema.md sobre um Excel.")
    parser.add_argument("--excel", required=True, help="Caminho do arquivo Excel de entrada")
    parser.add_argument("--schema", required=True, help="Caminho do schema.md")
    parser.add_argument("--saida", default="dados_tratado.xlsx", help="Caminho do Excel de saída")
    args = parser.parse_args()

    print(f"Lendo schema: {args.schema}")
    tables = parse_schema_md(args.schema)
    print(f"Tabelas encontradas no schema: {list(tables.keys())}")

    print(f"Lendo excel: {args.excel}")
    sheets = pd.read_excel(args.excel, sheet_name=None)

    all_errors = []
    treated_sheets = {}

    for sheet_name, df in sheets.items():
        table_name = SHEET_TABLE_MAP.get(sheet_name, sheet_name.strip().lower())
        if table_name not in tables:
            print(f"[AVISO] Aba '{sheet_name}' não corresponde a nenhuma tabela do schema — copiada sem tratamento.")
            treated_sheets[sheet_name] = df
            continue

        print(f"Aplicando regras da tabela '{table_name}' à aba '{sheet_name}'...")
        cleaned_df, errors = apply_schema_to_dataframe(df, table_name, tables[table_name]["columns"])
        treated_sheets[sheet_name] = cleaned_df
        all_errors.extend(errors)

    # Aba de log consolidado
    log_df = pd.DataFrame(all_errors) if all_errors else pd.DataFrame(
        columns=["tabela", "linha", "coluna", "valor_original", "problema", "acao"]
    )

    # Resumo por tabela
    if not log_df.empty:
        resumo = (
            log_df[log_df["problema"] != "-"]
            .groupby("tabela")
            .size()
            .reset_index(name="qtd_erros")
        )
    else:
        resumo = pd.DataFrame(columns=["tabela", "qtd_erros"])

    with pd.ExcelWriter(args.saida, engine="openpyxl") as writer:
        for sheet_name, df in treated_sheets.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        log_df.to_excel(writer, sheet_name="log_validacao", index=False)
        resumo.to_excel(writer, sheet_name="resumo", index=False)

    print(f"\nConcluído. Arquivo tratado salvo em: {args.saida}")
    print(f"Total de ocorrências registradas no log: {len(all_errors)}")


if __name__ == "__main__":
    main()
