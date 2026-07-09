from apps.accounting.models import AccountingDimension
from apps.projects.models import Project

from .commands import ProjectCodeSuggestion, SuggestNextProjectCodeCommand


class ProjectCodeAllocationService:
    """Suggest project codes from local Workspace and accounting cache data.

    This service is read-only: it does not create projects, dimensions, or
    external Merit records. Later project creation workflows can use this
    suggestion as evidence before asking the user to confirm.
    """

    @staticmethod
    def suggest_next_code(command: SuggestNextProjectCodeCommand) -> ProjectCodeSuggestion:
        metadata = dict(command.metadata or {})
        prefix = str(command.prefix or "")

        project_codes = list(
            Project.objects.filter(organization=command.organization).values_list("code", flat=True)
        )
        dimension_codes = list(
            AccountingDimension.objects.filter(
                organization=command.organization,
                dimension_type=AccountingDimension.DimensionType.PROJECT,
                is_active=True,
            ).values_list("code", flat=True)
        )

        used_codes = sorted({str(code) for code in [*project_codes, *dimension_codes] if code})
        suggested_code = ProjectCodeAllocationService._suggest_code(
            used_codes=used_codes,
            prefix=prefix,
            min_code=command.min_code,
        )

        return ProjectCodeSuggestion(
            suggested_code=suggested_code,
            used_codes=used_codes,
            source_summary={
                "project_codes_count": len(project_codes),
                "accounting_dimension_codes_count": len(dimension_codes),
                "used_numeric_codes_count": ProjectCodeAllocationService._count_numeric_codes(
                    used_codes,
                    prefix=prefix,
                ),
                "prefix": prefix,
                "min_code": command.min_code,
            },
            metadata=metadata,
        )

    @staticmethod
    def _suggest_code(*, used_codes: list[str], prefix: str, min_code: object) -> str:
        if prefix:
            return ProjectCodeAllocationService._suggest_prefixed_code(
                used_codes=used_codes,
                prefix=prefix,
                min_code=min_code,
            )

        numeric_values = sorted(int(code) for code in used_codes if code.isdigit())
        start = ProjectCodeAllocationService._coerce_int(min_code)
        if start is None:
            start = (numeric_values[-1] + 1) if numeric_values else 1

        used_numeric = set(numeric_values)
        candidate = start
        while candidate in used_numeric:
            candidate += 1
        return str(candidate)

    @staticmethod
    def _suggest_prefixed_code(*, used_codes: list[str], prefix: str, min_code: object) -> str:
        suffixes: list[tuple[int, int]] = []
        for code in used_codes:
            if not code.startswith(prefix):
                continue

            suffix = code[len(prefix) :]
            if suffix.isdigit() and suffix:
                suffixes.append((int(suffix), len(suffix)))

        min_suffix = ProjectCodeAllocationService._coerce_prefixed_min_code(prefix, min_code)
        if min_suffix is not None:
            start = min_suffix
        elif suffixes:
            start = max(value for value, _width in suffixes) + 1
        else:
            start = 1

        used_suffixes = {value for value, _width in suffixes}
        width = max((width for _value, width in suffixes), default=0)
        candidate = start
        while candidate in used_suffixes:
            candidate += 1

        suffix = str(candidate).zfill(width) if width else str(candidate)
        return f"{prefix}{suffix}"

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        if value is None:
            return None

        value_as_text = str(value)
        if value_as_text.isdigit():
            return int(value_as_text)
        return None

    @staticmethod
    def _coerce_prefixed_min_code(prefix: str, min_code: object) -> int | None:
        if min_code is None:
            return None

        min_code_text = str(min_code)
        if min_code_text.startswith(prefix):
            suffix = min_code_text[len(prefix) :]
            return int(suffix) if suffix.isdigit() and suffix else None

        return ProjectCodeAllocationService._coerce_int(min_code)

    @staticmethod
    def _count_numeric_codes(used_codes: list[str], prefix: str) -> int:
        if not prefix:
            return sum(1 for code in used_codes if code.isdigit())

        return sum(
            1
            for code in used_codes
            if code.startswith(prefix) and code[len(prefix) :].isdigit() and code[len(prefix) :]
        )
