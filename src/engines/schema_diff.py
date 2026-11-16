"""
Schema Drift Impact Analyzer
IBD 2.0 - Theme 07

Purpose:
    Compare before and after source schemas.
    Detect:
        1. Added columns
        2. Dropped columns
        3. Renamed columns
        4. Changed column data types

Important:
    Rename detection requires an explicit rename hint.
    A dropped column and an added column are not automatically
    assumed to be a rename.

Public functions:
    load_json(path)
    compare_schemas(before, after, seeded_changes=None)
"""

from __future__ import annotations

import argparse
import json
import re

from pathlib import Path
from typing import Any


# Supported change types
SUPPORTED_CHANGE_TYPES = {
    "rename",
    "drop",
    "add",
    "type change"
}

# Supports both Unicode and ASCII arrows
ARROW_PATTERN = re.compile(r"\s*(?:→|->)\s*")


# ---------------------------------------------------------
# 1. LOAD JSON FILES
# ---------------------------------------------------------

def load_json(path: str | Path) -> Any:
    """
    Load a JSON file.

    Args:
        path: JSON file path.

    Returns:
        Parsed JSON content.
    """

    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


# ---------------------------------------------------------
# 2. EXTRACT AND VALIDATE COLUMNS
# ---------------------------------------------------------

def _columns_by_name(
    table_schema: dict[str, Any]
) -> dict[str, str]:
    """
    Convert a table schema into:

        {
            "column_name": "data_type"
        }

    Validates column names, types and duplicate columns.
    """

    if not isinstance(table_schema, dict):
        raise ValueError(
            "Table schema must be a JSON object."
        )

    columns = table_schema.get("columns", [])

    if not isinstance(columns, list):
        raise ValueError(
            "Table schema 'columns' must be a list."
        )

    result = {}

    for column in columns:

        if not isinstance(column, dict):
            raise ValueError(
                f"Invalid column definition: {column}"
            )

        name = column.get("name")
        data_type = column.get("type")

        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"Invalid column name: {column}"
            )

        if (
            not isinstance(data_type, str)
            or not data_type.strip()
        ):
            raise ValueError(
                f"Invalid column type: {column}"
            )

        name = name.strip()
        data_type = data_type.strip()

        if name in result:
            raise ValueError(
                f"Duplicate column name: {name}"
            )

        result[name] = data_type

    return result


# ---------------------------------------------------------
# 3. PARSE EXPLICIT CHANGE METADATA
# ---------------------------------------------------------

def _parse_seed_column(
    change: dict[str, Any]
) -> tuple[str | None, str | None]:
    """
    Extract column names from explicit change metadata.

    Returns:
        (old_column_name, new_column_name)

    Rename:
        email -> email_address

    Drop:
        discount_amount dropped

    Add:
        brand varchar(100) added

    Type change:
        unit_price decimal(18,2) -> varchar(20)
    """

    detail = str(
        change.get("detail", "")
    ).strip()

    change_type = str(
        change.get("change_type", "")
    ).strip().lower()

    # Rename
    if change_type == "rename":

        parts = ARROW_PATTERN.split(
            detail,
            maxsplit=1
        )

        if len(parts) != 2:
            return None, None

        old_name = parts[0].strip()
        new_name = parts[1].strip()

        return (
            old_name or None,
            new_name or None
        )

    # Drop or type change
    if change_type in {"drop", "type change"}:

        match = re.match(
            r"^([^\s:]+)",
            detail
        )

        return (
            match.group(1),
            None
        ) if match else (None, None)

    # Add
    if change_type == "add":

        match = re.match(
            r"^([^\s:]+)",
            detail
        )

        return (
            None,
            match.group(1)
        ) if match else (None, None)

    return None, None


# ---------------------------------------------------------
# 4. VALIDATE COMPLETE SCHEMA SNAPSHOT
# ---------------------------------------------------------

def _validate_snapshot(
    snapshot: dict[str, Any],
    label: str
) -> None:
    """
    Validate the complete source schema snapshot.
    """

    if not isinstance(snapshot, dict):
        raise ValueError(
            f"{label} schema snapshot must be an object."
        )

    for table_name, table_schema in snapshot.items():

        if (
            not isinstance(table_name, str)
            or not table_name.strip()
        ):
            raise ValueError(
                f"{label} snapshot contains an invalid table name."
            )

        _columns_by_name(table_schema)


# ---------------------------------------------------------
# 5. INDEX SEEDED CHANGE METADATA
# ---------------------------------------------------------

def _seed_indexes(
    seeded_changes: dict[str, Any] | None
):
    """
    Build indexes from optional metadata.

    Metadata is used to:
        - Associate change IDs with detected changes.
        - Provide explicit rename hints.

    It does not hardcode expected outcomes.
    """

    if seeded_changes is None:
        return {}, {}, []

    if not isinstance(seeded_changes, dict):
        raise ValueError(
            "seeded_changes must be an object."
        )

    seeds = seeded_changes.get("changes", [])

    if not isinstance(seeds, list):
        raise ValueError(
            "seeded_changes['changes'] must be a list."
        )

    by_source_column = {}
    rename_hints = {}

    for seed in seeds:

        if not isinstance(seed, dict):
            raise ValueError(
                f"Invalid seeded change: {seed}"
            )

        source = seed.get("source")

        change_type = str(
            seed.get("change_type", "")
        ).strip().lower()

        if (
            not isinstance(source, str)
            or not source.strip()
        ):
            continue

        if change_type not in SUPPORTED_CHANGE_TYPES:
            continue

        old_name, new_name = _parse_seed_column(seed)

        # Explicit rename hint
        if change_type == "rename":

            if old_name and new_name:

                rename_hints.setdefault(
                    source,
                    []
                ).append(
                    (old_name, new_name, seed)
                )

        # Added column
        elif change_type == "add" and new_name:

            by_source_column[
                (source, new_name)
            ] = seed

        # Dropped or type-changed column
        elif old_name:

            by_source_column[
                (source, old_name)
            ] = seed

    return (
        by_source_column,
        rename_hints,
        seeds
    )


# ---------------------------------------------------------
# 6. MAIN SCHEMA COMPARISON ENGINE
# ---------------------------------------------------------

def compare_schemas(
    before: dict[str, Any],
    after: dict[str, Any],
    seeded_changes: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """
    Compare two source schema snapshots.

    Args:
        before:
            Original schema snapshot.

        after:
            Updated schema snapshot.

        seeded_changes:
            Optional metadata containing change IDs
            and explicit rename hints.

    Returns:
        List of detected schema changes.

    Output record structure:

        {
            "change_id": "SC01",
            "source": "crm.customers",
            "change_type": "rename",
            "column_before": "email",
            "column_after": "email_address",
            "type_before": "string",
            "type_after": "string",
            "description": "email -> email_address"
        }
    """

    # Validate inputs
    _validate_snapshot(before, "before")
    _validate_snapshot(after, "after")

    (
        seeds_by_source_and_column,
        rename_hints,
        seeds
    ) = _seed_indexes(seeded_changes)

    records = []

    # Include tables present in either snapshot
    all_tables = sorted(
        set(before.keys()) | set(after.keys())
    )

    for table in all_tables:

        before_columns = (
            _columns_by_name(before[table])
            if table in before
            else {}
        )

        after_columns = (
            _columns_by_name(after[table])
            if table in after
            else {}
        )

        # Identify basic differences
        dropped = (
            set(before_columns.keys())
            - set(after_columns.keys())
        )

        added = (
            set(after_columns.keys())
            - set(before_columns.keys())
        )

        common = (
            set(before_columns.keys())
            & set(after_columns.keys())
        )

        # -------------------------------------------------
        # A. DETECT RENAMED COLUMNS
        # -------------------------------------------------

        for (
            old_name,
            new_name,
            seed
        ) in rename_hints.get(table, []):

            # A rename is accepted only when:
            # - old column existed before
            # - old column is absent after
            # - new column is present after

            if (
                old_name in dropped
                and new_name in added
            ):

                records.append({

                    "change_id": seed.get("change_id"),

                    "source": table,

                    "change_type": "rename",

                    "column_before": old_name,

                    "column_after": new_name,

                    "type_before": before_columns[old_name],

                    "type_after": after_columns[new_name],

                    "description": (
                        f"{old_name} → {new_name}"
                    )
                })

                dropped.remove(old_name)
                added.remove(new_name)

        # -------------------------------------------------
        # B. DETECT DROPPED COLUMNS
        # -------------------------------------------------

        for column_name in sorted(dropped):

            seed = seeds_by_source_and_column.get(
                (table, column_name),
                {}
            )

            records.append({

                "change_id": seed.get("change_id"),

                "source": table,

                "change_type": "drop",

                "column_before": column_name,

                "column_after": None,

                "type_before": before_columns[column_name],

                "type_after": None,

                "description": (
                    f"{column_name} dropped"
                )
            })

        # -------------------------------------------------
        # C. DETECT ADDED COLUMNS
        # -------------------------------------------------

        for column_name in sorted(added):

            seed = seeds_by_source_and_column.get(
                (table, column_name),
                {}
            )

            records.append({

                "change_id": seed.get("change_id"),

                "source": table,

                "change_type": "add",

                "column_before": None,

                "column_after": column_name,

                "type_before": None,

                "type_after": after_columns[column_name],

                "description": (
                    f"{column_name} added"
                )
            })

        # -------------------------------------------------
        # D. DETECT DATA TYPE CHANGES
        # -------------------------------------------------

        for column_name in sorted(common):

            before_type = before_columns[column_name]
            after_type = after_columns[column_name]

            # Ignore case-only differences
            if (
                before_type.casefold()
                != after_type.casefold()
            ):

                seed = seeds_by_source_and_column.get(
                    (table, column_name),
                    {}
                )

                records.append({

                    "change_id": seed.get("change_id"),

                    "source": table,

                    "change_type": "type change",

                    "column_before": column_name,

                    "column_after": column_name,

                    "type_before": before_type,

                    "type_after": after_type,

                    "description": (
                        f"{column_name}: "
                        f"{before_type} → {after_type}"
                    )
                })

    # -----------------------------------------------------
    # 7. DETERMINISTIC OUTPUT ORDER
    # -----------------------------------------------------

    seed_order = {
        item.get("change_id"): index
        for index, item in enumerate(seeds)
        if (
            isinstance(item, dict)
            and item.get("change_id")
        )
    }

    records.sort(
        key=lambda row: (
            seed_order.get(
                row.get("change_id"),
                len(seed_order)
            ),
            row["source"],
            (
                row["column_before"]
                or row["column_after"]
                or ""
            )
        )
    )

    # Fallback change_id for unseeded changes
    unseeded_idx = 1
    for row in records:
        if not row.get("change_id"):
            row["change_id"] = f"CHG-{unseeded_idx:02d}"
            unseeded_idx += 1

    return records


# ---------------------------------------------------------
# 8. COMMAND LINE EXECUTION
# ---------------------------------------------------------

def main() -> None:
    """
    Run schema comparison using the starter-kit files.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Schema Drift Impact Analyzer - "
            "Schema Comparison Engine"
        )
    )

    parser.add_argument(
        "--before",
        default="starter_kit/schemas/sources_before.json"
    )

    parser.add_argument(
        "--after",
        default="starter_kit/schemas/sources_after.json"
    )

    parser.add_argument(
        "--seeds",
        default="starter_kit/schemas/seeded_changes.json"
    )

    parser.add_argument(
        "--output",
        default="outputs/schema_diff.json"
    )

    args = parser.parse_args()

    # Load input files
    before = load_json(args.before)
    after = load_json(args.after)

    seeds = (
        load_json(args.seeds)
        if args.seeds
        else None
    )

    # Compare schemas
    changes = compare_schemas(
        before,
        after,
        seeds
    )

    # Save output
    output_path = Path(args.output)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output_path.write_text(
        json.dumps(changes, indent=2),
        encoding="utf-8"
    )

    # Display results
    print(
        f"Detected {len(changes)} schema changes."
    )

    for change in changes:

        print(
            f"{change.get('change_id') or 'UNSEEDED'} | "
            f"{change['source']} | "
            f"{change['change_type']} | "
            f"{change['description']}"
        )

    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
