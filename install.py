# Installer for New Belchertown WeeWX skin
# Pat O'Brien, 2018
# uajqq, 2024

import configobj
from setup import ExtensionInstaller
from io import BytesIO, StringIO
import os
import re
import sys

# -------- extension info -----------

VERSION = "2.0"
NAME = "new-belchertown"
DESCRIPTION = "A clean, modern skin with real time streaming updates and interactive charts."
AUTHOR = "Pat OBrien and uajqq"
AUTHOR_EMAIL = "https://github.com/uajqq/weewx-belchertown-new"

# -------- main loader -----------


def loader():
    return NewBelchertownInstaller()


class NewBelchertownInstaller(ExtensionInstaller):
    _NEW_REPORT_NAME = "new-belchertown"
    _OLD_REPORT_NAMES = ("Belchertown", "belchertown")
    _SKIN_CONF_REL_PATH = ("skins", "new-belchertown", "skin.conf")
    _NEW_BELCHERTOWN_ROOT_KEYS = {
        "skin": "new-belchertown",
        "HTML_ROOT": "new-belchertown",
        "enable": "true",
    }
    _EXTRAS_PLACEHOLDER_KEY = "required_section_placeholder"
    _LEGACY_PLACEHOLDER_KEYS = ("work_around_ConfigObj_limitations",)
    _LABEL_TYPO_NORMALIZATIONS = {
        "Servere": "Severe",
        "Hazadous": "Hazardous",
        " For ": " for ",
    }
    _LEGACY_EXTRAS_MAPPING = {
        "graph_page_show_all_button": "chart_page_show_all_button",
        "graph_page_default_graphgroup": "chart_page_default_chartgroup",
        "highcharts_homepage_graphgroup": "highcharts_homepage_chartgroup",
    }
    _LEGACY_LABELS_GENERIC_MAPPING = {
        "nav_graphs": "nav_charts",
        "graphs_page_header": "charts_page_header",
        "homepage_graphs_link": "homepage_charts_link",
        "graphs_page_all_button": "charts_page_all_button",
        "graphs_windrose_frequency": "charts_windrose_frequency",
        "graphs_windDir_ordinals": "charts_windDir_ordinals",
    }
    _SKIN_DEFAULTS_CACHE = None
    _SKIN_ALIGNMENT_CACHE = None

    @classmethod
    def _normalize_old_belchertown_path(cls, value, allow_bare=False):
        """Rewrite old Belchertown folder references to New Belchertown."""
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if stripped.lower() == "belchertown":
            return cls._NEW_REPORT_NAME if allow_bare else value

        def replace_segment(match):
            return "%s%s" % (match.group(1), cls._NEW_REPORT_NAME)

        return re.sub(
            r"(^|[/\\])belchertown(?=$|[/\\])",
            replace_segment,
            value,
            flags=re.IGNORECASE,
        )

    @classmethod
    def _normalize_old_belchertown_paths(cls, value):
        """Recursively normalize Belchertown path values in config data."""
        if isinstance(value, str):
            return cls._normalize_old_belchertown_path(value)
        if isinstance(value, list):
            return [cls._normalize_old_belchertown_paths(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._normalize_old_belchertown_paths(item) for item in value)
        if isinstance(value, (dict, configobj.Section)):
            return {
                key: cls._normalize_old_belchertown_paths(item)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _should_normalize_extra_value(key):
        """Return True if an Extras value should be treated as a path/html value."""
        return not str(key).startswith("mqtt_")

    @staticmethod
    def _section_to_dict(section):
        """Convert a ConfigObj section to a plain nested dict."""
        if not isinstance(section, (dict, configobj.Section)):
            return {}

        result = {}
        for key, value in section.items():
            if isinstance(value, (dict, configobj.Section)):
                result[key] = NewBelchertownInstaller._section_to_dict(value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _leading_spaces(text):
        """Return the number of leading spaces in text."""
        return len(text) - len(text.lstrip(" "))

    @classmethod
    def _format_config_value(cls, value):
        """Format a Python/ConfigObj value back into config syntax."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            if '"' in value and "'" not in value:
                # Preserve HTML attributes without adding backslash escapes.
                escaped = value.replace("\\", "\\\\")
                return "'%s'" % escaped
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return '"%s"' % escaped
        if isinstance(value, (list, tuple)):
            return ", ".join(cls._format_config_value(item) for item in value)
        return str(value)

    @classmethod
    def _format_config_assignment(cls, key, value, key_part=None):
        """Format a key/value pair back into config syntax."""
        if key_part is not None:
            return "%s= %s" % (key_part, cls._format_config_value(value))
        return "%s = %s" % (key, cls._format_config_value(value))

    @classmethod
    def _extract_alignment_key_parts(cls, source_lines):
        """Return skin.conf key spacing for later ConfigObj output alignment."""
        key_parts = {}
        non_empty_lines = [line for line in source_lines if line.strip()]
        base_indent = min(
            (cls._leading_spaces(line) for line in non_empty_lines),
            default=0,
        )

        for raw_line in source_lines:
            line = raw_line.rstrip("\n")
            if base_indent and len(line) >= base_indent:
                content = line[base_indent:]
            else:
                content = line.lstrip(" ")

            stripped = content.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("["):
                continue
            if "=" not in content:
                continue

            key_part, _ = content.split("=", 1)
            key = key_part.strip()
            if key and not cls._is_placeholder_key(key):
                key_parts[key] = key_part

        return key_parts

    @classmethod
    def _get_skin_alignment_key_parts(cls):
        """Load and cache skin.conf assignment columns."""
        if cls._SKIN_ALIGNMENT_CACHE is not None:
            return cls._SKIN_ALIGNMENT_CACHE

        skin_path = cls._skin_conf_path()
        if not os.path.isfile(skin_path):
            cls._SKIN_ALIGNMENT_CACHE = {}
            return cls._SKIN_ALIGNMENT_CACHE

        try:
            with open(skin_path, "r", encoding="utf-8") as skin_file:
                skin_lines = skin_file.readlines()
        except Exception:
            cls._SKIN_ALIGNMENT_CACHE = {}
            return cls._SKIN_ALIGNMENT_CACHE

        alignment = {}
        alignment.update(
            cls._extract_alignment_key_parts(
                cls._extract_skin_section_lines(skin_lines, "Extras")
            )
        )
        alignment.update(
            cls._extract_alignment_key_parts(
                cls._extract_skin_section_lines(skin_lines, "Labels", "Generic")
            )
        )
        cls._SKIN_ALIGNMENT_CACHE = alignment
        return cls._SKIN_ALIGNMENT_CACHE

    @classmethod
    def _align_new_belchertown_config_text(cls, config_text):
        """Align and space New Belchertown's serialized config section."""
        alignment = cls._get_skin_alignment_key_parts()

        rendered_lines = []
        in_stdreport = False
        in_belchertown = False
        in_extras = False
        extras_option_indent = None

        def section_marker_level(stripped):
            if not stripped.startswith("[") or not stripped.endswith("]"):
                return 0
            opening = len(stripped) - len(stripped.lstrip("["))
            closing = len(stripped) - len(stripped.rstrip("]"))
            if opening != closing:
                return 0
            return opening

        def append_blank_line_if_needed(newline):
            if rendered_lines and rendered_lines[-1].strip():
                rendered_lines.append(newline or "\n")

        for raw_line in config_text.splitlines(True):
            body = raw_line.rstrip("\r\n")
            newline = raw_line[len(body) :]
            stripped = body.strip()

            if stripped.startswith("[") and stripped.endswith("]"):
                marker_level = section_marker_level(stripped)
                if in_belchertown and marker_level and marker_level <= 2:
                    append_blank_line_if_needed(newline)

                if marker_level >= 3:
                    section_name = stripped[3:-3].strip()
                    in_extras = in_belchertown and section_name == "Extras"
                    if in_extras:
                        marker_indent = body[: len(body) - len(body.lstrip(" "))]
                        extras_option_indent = marker_indent + "    "
                    else:
                        extras_option_indent = None
                elif marker_level == 2:
                    section_name = stripped[2:-2].strip()
                    in_belchertown = (
                        in_stdreport and section_name == cls._NEW_REPORT_NAME
                    )
                    if in_belchertown:
                        append_blank_line_if_needed(newline)
                    in_extras = False
                    extras_option_indent = None
                elif marker_level == 1:
                    section_name = stripped[1:-1].strip()
                    in_stdreport = section_name == "StdReport"
                    in_belchertown = False
                    in_extras = False
                    extras_option_indent = None
                rendered_lines.append(raw_line)
                continue

            if in_extras and stripped.startswith("#") and extras_option_indent is not None:
                body = extras_option_indent + body.lstrip(" ")
                raw_line = body + newline

            if in_extras and stripped and not stripped.startswith("#") and "=" in body:
                leading = body[: len(body) - len(body.lstrip(" "))]
                content = body[len(leading) :]
                key_part, raw_value = content.split("=", 1)
                aligned_key_part = alignment.get(key_part.strip())
                if aligned_key_part is not None:
                    body = "%s%s= %s" % (
                        leading,
                        aligned_key_part,
                        raw_value.lstrip(),
                    )
                    raw_line = body + newline

            rendered_lines.append(raw_line)

        if in_belchertown:
            append_blank_line_if_needed("\n")

        return "".join(rendered_lines)

    @classmethod
    def _install_aligned_config_writer(cls):
        """Patch ConfigObj output for New Belchertown's generated config section."""
        if getattr(configobj.ConfigObj, "_new_belchertown_original_write", None):
            return

        original_write = configobj.ConfigObj.write

        def aligned_write(config_self, outfile=None, section=None):
            if section is not None:
                return original_write(config_self, outfile, section)

            encoding = (
                config_self.encoding
                or config_self.default_encoding
                or "ascii"
            )

            if outfile is None and config_self.filename is None:
                output = original_write(config_self, outfile=None, section=None)
                if not output:
                    return output
                output_is_bytes = isinstance(output[0], bytes)
                if output_is_bytes:
                    text = "\n".join(line.decode(encoding) for line in output)
                else:
                    text = "\n".join(output)
                text = NewBelchertownInstaller._align_new_belchertown_config_text(text)
                lines = text.split("\n")
                if output_is_bytes:
                    return [line.encode(encoding) for line in lines]
                return lines

            stream = BytesIO()
            original_write(config_self, stream, section=None)
            text = stream.getvalue().decode(encoding)
            text = NewBelchertownInstaller._align_new_belchertown_config_text(text)
            output_bytes = text.encode(encoding)

            if outfile is not None:
                outfile.write(output_bytes)
            else:
                with open(config_self.filename, "wb") as output_file:
                    output_file.write(output_bytes)

        configobj.ConfigObj._new_belchertown_original_write = original_write
        configobj.ConfigObj.write = aligned_write

    @staticmethod
    def _split_value_comment(value_text):
        """Split a config value from an inline comment, if present."""
        in_single = False
        in_double = False

        for index, char in enumerate(value_text):
            if char == '"' and not in_single:
                in_double = not in_double
            elif char == "'" and not in_double:
                in_single = not in_single
            elif char == "#" and not in_single and not in_double:
                return value_text[:index].rstrip(), value_text[index:].rstrip()

        return value_text.rstrip(), ""

    @classmethod
    def _parse_config_value(cls, value_text):
        """Parse a raw config value string using ConfigObj semantics."""
        try:
            parsed = configobj.ConfigObj(StringIO("x = %s" % value_text), encoding="utf-8")
            return parsed.get("x")
        except Exception:
            return value_text

    @classmethod
    def _guess_weewx_config_path(cls, engine, current_config):
        """Best-effort path lookup for weewx.conf used by the installer."""
        candidates = []

        if hasattr(current_config, "filename"):
            candidates.append(getattr(current_config, "filename"))

        for attr in ("config_path", "config_file", "config_filename", "config_fn"):
            if hasattr(engine, attr):
                candidates.append(getattr(engine, attr))

        for candidate in candidates:
            if isinstance(candidate, str) and candidate and os.path.isfile(candidate):
                return candidate

        return None

    @classmethod
    def _extract_skin_section_lines(cls, skin_lines, top_level_name, nested_name=None):
        """Extract raw lines for a top-level or nested section from skin.conf."""
        collected = []
        current_top = None
        inside_nested = nested_name is None

        for line in skin_lines:
            stripped = line.strip()

            if stripped.startswith("[") and not stripped.startswith("[["):
                current_top = stripped[1:-1].strip()
                if current_top != top_level_name and collected:
                    break
                inside_nested = nested_name is None
                continue

            if current_top != top_level_name:
                continue

            if nested_name is None:
                collected.append(line)
                continue

            if stripped.startswith("[[") and stripped.endswith("]]"):
                nested_section = stripped[2:-2].strip()
                if nested_section == nested_name:
                    inside_nested = True
                    continue
                if inside_nested and collected:
                    break
                inside_nested = False
                continue

            if inside_nested:
                collected.append(line)

        return collected

    @classmethod
    def _extract_commented_extra_overrides(
        cls,
        engine,
        current_config,
        report_names=None,
    ):
        """Extract commented-out Extras options that differ from skin.conf defaults."""
        default_extras, _ = cls._get_skin_defaults()
        if not default_extras:
            return {}

        report_names = tuple(
            report_names or ((cls._NEW_REPORT_NAME,) + cls._OLD_REPORT_NAMES)
        )
        config_path = cls._guess_weewx_config_path(engine, current_config)
        if not config_path:
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return {}

        in_stdreport = False
        in_belchertown = False
        in_extras = False
        commented_overrides = {}

        for raw_line in lines:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if not stripped:
                continue

            if stripped.startswith("[") and stripped.endswith("]"):
                if stripped.startswith("[[["):
                    section_name = stripped[3:-3].strip()
                    in_extras = in_belchertown and section_name == "Extras"
                    continue

                if stripped.startswith("[["):
                    section_name = stripped[2:-2].strip()
                    in_belchertown = in_stdreport and section_name in report_names
                    in_extras = False
                    continue

                section_name = stripped[1:-1].strip()
                in_stdreport = section_name == "StdReport"
                in_belchertown = False
                in_extras = False
                continue

            if not in_extras:
                continue

            content = stripped
            if not content.startswith("#"):
                continue

            content = content[1:].lstrip()
            if not content or content.startswith("#"):
                continue
            if "=" not in content:
                continue

            key_part, raw_value = content.split("=", 1)
            key = key_part.strip()
            if not key or cls._is_placeholder_key(key):
                continue

            parsed_value_text, inline_comment = cls._split_value_comment(raw_value)
            parsed_value = cls._parse_config_value(parsed_value_text)
            if cls._should_normalize_extra_value(key):
                parsed_value = cls._normalize_old_belchertown_paths(parsed_value)
            if key not in default_extras:
                continue

            default_value = default_extras[key]
            if parsed_value != default_value:
                commented_overrides[key] = (parsed_value, inline_comment)

        return commented_overrides

    @classmethod
    def _skin_conf_path(cls):
        """Return the canonical absolute path to skins/new-belchertown/skin.conf."""
        return os.path.join(os.path.dirname(__file__), *cls._SKIN_CONF_REL_PATH)

    @classmethod
    def _get_skin_defaults(cls):
        """Load and cache skin.conf defaults for Extras and Labels/Generic."""
        if cls._SKIN_DEFAULTS_CACHE is not None:
            return cls._SKIN_DEFAULTS_CACHE

        skin_path = cls._skin_conf_path()
        if not os.path.isfile(skin_path):
            cls._SKIN_DEFAULTS_CACHE = ({}, {})
            return cls._SKIN_DEFAULTS_CACHE

        try:
            skin_defaults = configobj.ConfigObj(skin_path, encoding="utf-8")
            default_extras = cls._section_to_dict(skin_defaults.get("Extras", {}))
            default_generic = cls._section_to_dict(
                skin_defaults.get("Labels", {}).get("Generic", {})
            )
        except Exception:
            cls._SKIN_DEFAULTS_CACHE = ({}, {})
            return cls._SKIN_DEFAULTS_CACHE

        cls._SKIN_DEFAULTS_CACHE = (default_extras, default_generic)
        return cls._SKIN_DEFAULTS_CACHE

    @classmethod
    def _render_skin_lines(
        cls,
        source_lines,
        target_indent,
        restored_values,
        placeholder_key,
        commented_value_overrides=None,
        legacy_value_overrides=None,
        legacy_insert_before=None,
        legacy_insert_end=None,
    ):
        """Render skin.conf lines as commented defaults plus restored active values."""
        rendered = []
        commented_value_overrides = commented_value_overrides or {}
        legacy_value_overrides = legacy_value_overrides or {}
        legacy_insert_before = legacy_insert_before or {}
        legacy_insert_end = legacy_insert_end or []
        rendered_active_keys = set()
        non_empty_lines = [line for line in source_lines if line.strip()]
        base_indent = min(
            (cls._leading_spaces(line) for line in non_empty_lines),
            default=0,
        )

        for raw_line in source_lines:
            line = raw_line.rstrip("\n")

            if base_indent and len(line) >= base_indent:
                content = line[base_indent:]
            else:
                content = line.lstrip(" ")

            stripped = content.strip()
            if not stripped:
                rendered.append("")
                continue

            if stripped.startswith("#"):
                rendered.append(target_indent + stripped)
                continue

            if stripped.startswith("["):
                continue

            if "=" not in content:
                rendered.append(target_indent + stripped)
                continue

            key_part, raw_value = content.split("=", 1)
            key = key_part.strip()

            if key == placeholder_key:
                continue

            legacy_before_keys = legacy_insert_before.get(key, [])
            for legacy_key in legacy_before_keys:
                if legacy_key in legacy_value_overrides:
                    legacy_line = cls._format_config_assignment(
                        legacy_key,
                        legacy_value_overrides[legacy_key],
                    )
                    rendered.append(target_indent + legacy_line)
                    rendered_active_keys.add(legacy_key)

            _, inline_comment = cls._split_value_comment(raw_value)
            active_value = restored_values.get(key)

            if active_value is None:
                commented_override = commented_value_overrides.get(key)
                if commented_override is not None:
                    commented_value, commented_inline = commented_override
                    commented_line = cls._format_config_assignment(
                        key,
                        commented_value,
                        key_part,
                    )
                    chosen_inline = commented_inline or inline_comment
                    if chosen_inline:
                        commented_line = "%s  %s" % (commented_line, chosen_inline)
                    rendered.append(target_indent + "# " + commented_line)
                    continue

                rendered.append(target_indent + "# " + stripped)
                continue

            restored_line = cls._format_config_assignment(key, active_value, key_part)
            if inline_comment:
                restored_line = "%s  %s" % (restored_line, inline_comment)

            rendered.append(target_indent + restored_line)
            rendered_active_keys.add(key)

        for legacy_key in legacy_insert_end:
            if legacy_key in legacy_value_overrides:
                legacy_line = cls._format_config_assignment(
                    legacy_key,
                    legacy_value_overrides[legacy_key],
                )
                rendered.append(target_indent + legacy_line)
                rendered_active_keys.add(legacy_key)

        preserved_keys = [
            key
            for key in restored_values
            if key not in rendered_active_keys and not cls._is_placeholder_key(key)
        ]
        if preserved_keys:
            if rendered and rendered[-1]:
                rendered.append("")
            rendered.append(target_indent + "# ----- Preserved custom Extras -----")
            for key in preserved_keys:
                rendered.append(
                    target_indent
                    + cls._format_config_assignment(key, restored_values[key])
                )

        return rendered

    @classmethod
    def _extract_report_overrides(cls, current_report):
        """Return report-level options that the New Belchertown rebuild does not own."""
        if not isinstance(current_report, (dict, configobj.Section)):
            return {}

        owned_keys = set(cls._NEW_BELCHERTOWN_ROOT_KEYS)
        owned_keys.update(("Extras", "Labels"))

        report_overrides = {}
        for key, value in current_report.items():
            if key in owned_keys:
                continue
            if isinstance(value, (dict, configobj.Section)):
                report_overrides[key] = cls._normalize_old_belchertown_paths(
                    cls._section_to_dict(value)
                )
            else:
                report_overrides[key] = cls._normalize_old_belchertown_paths(value)

        return report_overrides

    @classmethod
    def _known_new_belchertown_option_keys(cls):
        """Return option names owned by New Belchertown's generated config."""
        default_extras, default_generic = cls._get_skin_defaults()
        known_keys = set(cls._NEW_BELCHERTOWN_ROOT_KEYS)
        known_keys.update(default_extras)
        known_keys.update(default_generic)
        known_keys.update(cls._LEGACY_EXTRAS_MAPPING)
        known_keys.update(cls._LEGACY_EXTRAS_MAPPING.values())
        known_keys.update(cls._LEGACY_LABELS_GENERIC_MAPPING)
        known_keys.update(cls._LEGACY_LABELS_GENERIC_MAPPING.values())
        known_keys.update(cls._LEGACY_PLACEHOLDER_KEYS)
        known_keys.add(cls._EXTRAS_PLACEHOLDER_KEY)
        return known_keys

    @staticmethod
    def _section_names(section):
        """Return ConfigObj subsection names, falling back to dict order."""
        section_names = getattr(section, "sections", None)
        if section_names is not None:
            return list(section_names)

        names = []
        for key, value in section.items():
            if isinstance(value, (dict, configobj.Section)):
                names.append(key)
        return names

    @classmethod
    def _is_old_belchertown_report(cls, report):
        """Return True if a report section points at the old Belchertown skin."""
        if not isinstance(report, (dict, configobj.Section)):
            return False

        skin = str(report.get("skin", "")).strip().lower()
        html_root = str(report.get("HTML_ROOT", "")).strip().lower()
        return skin == "belchertown" or html_root == "belchertown"

    @classmethod
    def _find_old_belchertown_report_name(cls, std_report):
        """Find the report section for an old Belchertown install."""
        if not isinstance(std_report, (dict, configobj.Section)):
            return None

        report_names = cls._section_names(std_report)
        for old_name in cls._OLD_REPORT_NAMES:
            if old_name in report_names:
                return old_name

        for report_name in report_names:
            if str(report_name).lower() == "belchertown":
                return report_name

        for report_name in report_names:
            if cls._is_old_belchertown_report(std_report.get(report_name)):
                return report_name

        return None

    @classmethod
    def _comment_line_has_new_belchertown_option(cls, line, known_keys):
        """Return True if a comment line is a commented New Belchertown assignment."""
        content = str(line).strip()
        if not content.startswith("#"):
            return False

        content = content[1:].lstrip()
        if not content or content.startswith("#") or "=" not in content:
            return False

        key_part, _ = content.split("=", 1)
        key = key_part.strip()
        return key in known_keys

    @classmethod
    def _remove_new_belchertown_comment_groups(cls, comments, known_keys):
        """Remove contiguous comment groups that contain New Belchertown options."""
        cleaned = []
        group = []
        group_has_belchertown_option = False
        pending_blanks = []
        changed = False

        def flush_group():
            nonlocal group, group_has_belchertown_option, pending_blanks, changed

            if not group:
                return

            if group_has_belchertown_option:
                changed = True
                pending_blanks = []
            else:
                cleaned.extend(pending_blanks)
                cleaned.extend(group)
                pending_blanks = []

            group = []
            group_has_belchertown_option = False

        for comment in comments:
            if not str(comment).strip():
                flush_group()
                pending_blanks.append(comment)
                continue

            group.append(comment)
            if cls._comment_line_has_new_belchertown_option(comment, known_keys):
                group_has_belchertown_option = True

        flush_group()
        cleaned.extend(pending_blanks)

        if changed and not any(str(comment).strip() for comment in cleaned):
            cleaned = [""]

        return cleaned, changed

    @classmethod
    def _cleanup_following_report_comments(cls, std_report):
        """Drop stale New Belchertown comments attached to the next report section."""
        if not isinstance(std_report, (dict, configobj.Section)):
            return

        report_names = cls._section_names(std_report)
        candidates = [cls._NEW_REPORT_NAME]
        old_report_name = cls._find_old_belchertown_report_name(std_report)
        if old_report_name:
            candidates.append(old_report_name)
        candidates.extend(cls._OLD_REPORT_NAMES)
        comments_by_key = getattr(std_report, "comments", None)
        if not isinstance(comments_by_key, dict):
            return

        checked_reports = set()
        for report_name in candidates:
            if report_name in checked_reports or report_name not in report_names:
                continue
            checked_reports.add(report_name)
            report_index = report_names.index(report_name)
            if report_index + 1 >= len(report_names):
                continue

            next_report = report_names[report_index + 1]
            if next_report not in comments_by_key:
                continue

            comments = comments_by_key.get(next_report) or []
            cleaned_comments, changed = cls._remove_new_belchertown_comment_groups(
                comments,
                cls._known_new_belchertown_option_keys(),
            )
            if changed:
                comments_by_key[next_report] = cleaned_comments

    @classmethod
    def _build_new_belchertown_template(
        cls,
        current_report,
        commented_extra_overrides=None,
        legacy_extra_overrides=None,
        legacy_insert_before=None,
        legacy_insert_end=None,
    ):
        """Build a fresh New Belchertown section from skin.conf and old Extras values."""
        current_report = (
            current_report
            if isinstance(current_report, (dict, configobj.Section))
            else {}
        )
        current_extras = cls._extract_extra_overrides(
            current_report.get("Extras", {})
        )

        skin_path = cls._skin_conf_path()
        if not os.path.isfile(skin_path):
            return None

        with open(skin_path, "r", encoding="utf-8") as skin_file:
            skin_lines = skin_file.readlines()

        extras_lines = cls._extract_skin_section_lines(skin_lines, "Extras")

        root_values = {}
        for key, default_value in cls._NEW_BELCHERTOWN_ROOT_KEYS.items():
            root_values[key] = cls._normalize_old_belchertown_path(
                current_report.get(key, default_value),
                allow_bare=key in ("skin", "HTML_ROOT"),
            )

        template_lines = [
            "[StdReport]",
            "",
            "    [[new-belchertown]]",
            "        # See wiki for configuration help: https://github.com/uajqq/weewx-belchertown-new/wiki",
            '        skin = %s' % cls._format_config_value(root_values["skin"]),
            '        HTML_ROOT = %s' % cls._format_config_value(root_values["HTML_ROOT"]),
            '        enable = %s' % cls._format_config_value(root_values["enable"]),
            "",
            "        [[[Extras]]]",
            "",
        ]
        rendered_extras_lines = cls._render_skin_lines(
            extras_lines,
            "            ",
            current_extras,
            cls._EXTRAS_PLACEHOLDER_KEY,
            commented_extra_overrides,
            legacy_extra_overrides,
            legacy_insert_before,
            legacy_insert_end,
        )
        template_lines.extend(rendered_extras_lines)
        template_lines.append("")
        template_lines.extend(
            [
                "        [[[Labels]]]",
                "            [[[[Generic]]]]",
            ]
        )

        fresh_config = configobj.ConfigObj(
            StringIO("\n".join(template_lines)),
            encoding="utf-8",
        )
        belchertown = fresh_config.get("StdReport", {}).get("new-belchertown", {})
        if isinstance(belchertown, (dict, configobj.Section)):
            last_active_extra_index = -1
            for index, line in enumerate(rendered_extras_lines):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    last_active_extra_index = index

            # ConfigObj drops comment-only section tails unless they anchor to
            # the following section.
            labels_comments = rendered_extras_lines[last_active_extra_index + 1 :]
            while labels_comments and not labels_comments[-1].strip():
                labels_comments.pop()
            labels_comments.append("")
            belchertown.comments["Labels"] = labels_comments

        return fresh_config

    @classmethod
    def _extract_extra_overrides(cls, extras_section):
        """Return only user Extras overrides that differ from skin.conf defaults."""
        current_extras = cls._section_to_dict(extras_section)
        if not current_extras:
            return {}

        default_extras, _ = cls._get_skin_defaults()
        if not default_extras:
            # If defaults cannot be loaded, preserve existing extras to avoid data loss.
            return current_extras

        extra_overrides = {}
        for key, value in current_extras.items():
            if cls._is_placeholder_key(key):
                continue

            normalized_value = value
            if cls._should_normalize_extra_value(key):
                normalized_value = cls._normalize_old_belchertown_paths(value)
            if key not in default_extras or default_extras[key] != normalized_value:
                extra_overrides[key] = normalized_value

        return extra_overrides

    @classmethod
    def _is_placeholder_key(cls, key):
        """Return True if key is current or legacy placeholder sentinel."""
        return key == cls._EXTRAS_PLACEHOLDER_KEY or key in cls._LEGACY_PLACEHOLDER_KEYS

    @classmethod
    def _normalize_placeholder_in_section(cls, section):
        """Replace legacy placeholder keys with the current sentinel key in a section."""
        if not isinstance(section, (dict, configobj.Section)):
            return

        for legacy_key in cls._LEGACY_PLACEHOLDER_KEYS:
            if legacy_key not in section:
                continue

            if cls._EXTRAS_PLACEHOLDER_KEY not in section:
                section[cls._EXTRAS_PLACEHOLDER_KEY] = section[legacy_key]

            del section[legacy_key]

    @classmethod
    def _normalize_placeholder_keys_in_report(cls, current_report):
        """Normalize legacy placeholder keys in Extras and Labels/Generic."""
        if not isinstance(current_report, (dict, configobj.Section)):
            return

        extras = current_report.get("Extras")
        cls._normalize_placeholder_in_section(extras)

        labels = current_report.get("Labels")
        if isinstance(labels, (dict, configobj.Section)):
            generic = labels.get("Generic")
            cls._normalize_placeholder_in_section(generic)

    @classmethod
    def _detect_legacy_keys(cls, current_report):
        """Detect legacy key usage in Extras and Labels/Generic."""
        if not isinstance(current_report, (dict, configobj.Section)):
            return {"extras": {}, "labels_generic": {}}

        extras = cls._section_to_dict(current_report.get("Extras", {}))
        labels = current_report.get("Labels", {})
        labels_generic = {}
        if isinstance(labels, (dict, configobj.Section)):
            labels_generic = cls._section_to_dict(labels.get("Generic", {}))

        return {
            "extras": {
                key: cls._LEGACY_EXTRAS_MAPPING[key]
                for key in cls._LEGACY_EXTRAS_MAPPING
                if key in extras
            },
            "labels_generic": {
                key: cls._LEGACY_LABELS_GENERIC_MAPPING[key]
                for key in cls._LEGACY_LABELS_GENERIC_MAPPING
                if key in labels_generic
            },
        }

    @staticmethod
    def _legacy_prompt_choice(prompt_text):
        """Prompt user and return True for yes, False for no (default no)."""
        try:
            reply = input(prompt_text)
        except EOFError:
            return False
        except Exception:
            return False

        normalized = str(reply).strip().lower()
        return normalized in ("y", "yes")

    @staticmethod
    def _stdin_is_interactive():
        """Return True when installer prompts can be answered safely."""
        return hasattr(sys, "stdin") and sys.stdin and sys.stdin.isatty()

    @classmethod
    def _should_migrate_legacy_keys(cls, detected_legacy):
        """Offer legacy-key migration to users with a downgrade advisory."""
        has_extras = bool(detected_legacy.get("extras"))
        has_labels = bool(detected_legacy.get("labels_generic"))
        if not has_extras and not has_labels:
            return False

        if not cls._stdin_is_interactive():
            print("", flush=True)
            print("New Belchertown installer: legacy keys detected.", flush=True)
            print(
                "New Belchertown installer: non-interactive mode; "
                "skipping automatic migration to preserve downgrade compatibility.",
                flush=True,
            )
            print("", flush=True)
            return False

        print("\nNew Belchertown installer: detected deprecated key names in weewx.conf:\n")
        if has_extras:
            print("  [StdReport][new-belchertown][Extras]")
            for legacy_key, new_key in detected_legacy["extras"].items():
                print("    %s -> %s" % (legacy_key, new_key))
        if has_labels:
            print("  [StdReport][new-belchertown][Labels][Generic]")
            for legacy_key, new_key in detected_legacy["labels_generic"].items():
                print("    %s -> %s" % (legacy_key, new_key))

        print("\nWARNING: Migrating legacy keys updates your config to newer names.")
        print("WARNING: This can make downgrading to older versions harder.\n")

        return cls._legacy_prompt_choice(
            "Update these legacy keys to current names now? [y/N]: "
        )

    @classmethod
    def _migrate_legacy_keys_in_report(cls, current_report):
        """Migrate legacy key names in-place for Extras and Labels/Generic."""
        if not isinstance(current_report, (dict, configobj.Section)):
            return

        extras = current_report.get("Extras")
        if isinstance(extras, (dict, configobj.Section)):
            for legacy_key, new_key in cls._LEGACY_EXTRAS_MAPPING.items():
                if legacy_key in extras:
                    extras[new_key] = cls._normalize_old_belchertown_paths(
                        extras[legacy_key]
                    )
                    del extras[legacy_key]

        labels = current_report.get("Labels")
        if isinstance(labels, (dict, configobj.Section)):
            generic = labels.get("Generic")
            if isinstance(generic, (dict, configobj.Section)):
                for legacy_key, new_key in cls._LEGACY_LABELS_GENERIC_MAPPING.items():
                    if legacy_key in generic:
                        generic[new_key] = generic[legacy_key]
                        del generic[legacy_key]

    @classmethod
    def _extract_label_overrides(cls, labels_section):
        """Return only user label overrides that differ from skin.conf defaults."""
        if not isinstance(labels_section, (dict, configobj.Section)):
            return None

        _, default_generic = cls._get_skin_defaults()
        if not default_generic:
            # If defaults cannot be loaded, preserve existing labels to avoid data loss.
            return cls._section_to_dict(labels_section)

        current_labels = cls._section_to_dict(labels_section)
        current_generic = cls._section_to_dict(current_labels.get("Generic", {}))

        generic_overrides = {}
        for key, value in current_generic.items():
            if cls._is_placeholder_key(key):
                continue

            if key not in default_generic:
                generic_overrides[key] = value
                continue

            if default_generic[key] == value:
                continue

            normalized_value = value
            if isinstance(value, str):
                normalized_value = value
                for old, new in cls._LABEL_TYPO_NORMALIZATIONS.items():
                    normalized_value = normalized_value.replace(old, new)

            if default_generic[key] == normalized_value:
                continue

            generic_overrides[key] = value

        filtered_labels = {}
        for key, value in current_labels.items():
            if key == "Generic":
                continue
            filtered_labels[key] = value

        if generic_overrides:
            filtered_labels["Generic"] = generic_overrides

        return filtered_labels or None

    @classmethod
    def _build_legacy_extras_insert_plan(
        cls,
        extras_section,
        legacy_keys,
        known_default_keys,
        legacy_mapping,
    ):
        """Plan where to insert legacy keys based on their original Extras order."""
        insert_before = {}
        insert_end = []

        if not isinstance(extras_section, (dict, configobj.Section)):
            return insert_before, insert_end

        ordered_keys = list(extras_section.keys())
        legacy_set = set(legacy_keys)
        known_set = set(known_default_keys)

        for idx, key in enumerate(ordered_keys):
            if key not in legacy_set:
                continue

            mapped_key = legacy_mapping.get(key)
            if mapped_key in known_set and mapped_key not in legacy_set:
                insert_before.setdefault(mapped_key, []).append(key)
                continue

            anchor_key = None
            for candidate in ordered_keys[idx + 1 :]:
                if candidate in known_set and candidate not in legacy_set:
                    anchor_key = candidate
                    break

            if anchor_key is None:
                insert_end.append(key)
                continue

            insert_before.setdefault(anchor_key, []).append(key)

        return insert_before, insert_end

    @classmethod
    def _build_bootstrap_config(cls):
        """Build minimal installer config with empty nested sections.

        Fallback placeholder keys are added only if ConfigObj round-tripping
        proves empty sections are dropped in this runtime.
        """
        config = configobj.ConfigObj(encoding="utf-8")
        std_report = config.setdefault("StdReport", {})
        belchertown = std_report.setdefault("new-belchertown", {})

        for key, default_value in cls._NEW_BELCHERTOWN_ROOT_KEYS.items():
            belchertown[key] = default_value

        extras = belchertown.setdefault("Extras", {})
        labels = belchertown.setdefault("Labels", {})
        generic = labels.setdefault("Generic", {})
        belchertown.comments["Labels"] = [""]

        if not cls._empty_sections_survive_round_trip(config):
            extras[cls._EXTRAS_PLACEHOLDER_KEY] = "true"
            generic[cls._EXTRAS_PLACEHOLDER_KEY] = "true"

        return config

    @classmethod
    def _empty_sections_survive_round_trip(cls, config):
        """Return True if ConfigObj preserves empty nested sections when written/read."""
        try:
            try:
                stream = BytesIO()
                config.write(stream)
            except TypeError:
                stream = StringIO()
                config.write(stream)
            stream.seek(0)
            reparsed = configobj.ConfigObj(
                stream,
                encoding=getattr(config, "encoding", None) or "utf-8",
            )
        except Exception:
            return False

        std_report = reparsed.get("StdReport", {})
        belchertown = (
            std_report.get("new-belchertown", {})
            if isinstance(std_report, (dict, configobj.Section))
            else {}
        )
        extras = (
            belchertown.get("Extras")
            if isinstance(belchertown, (dict, configobj.Section))
            else None
        )
        labels = (
            belchertown.get("Labels")
            if isinstance(belchertown, (dict, configobj.Section))
            else None
        )
        generic = labels.get("Generic") if isinstance(labels, (dict, configobj.Section)) else None

        return (
            isinstance(extras, (dict, configobj.Section))
            and isinstance(labels, (dict, configobj.Section))
            and isinstance(generic, (dict, configobj.Section))
        )

    def configure(self, engine):
        """Rebuild New Belchertown root/Extras from skin.conf, preserving user overrides."""
        self._install_aligned_config_writer()
        current_config = engine.config_dict
        std_report = current_config.setdefault("StdReport", {})
        old_report_name = self._find_old_belchertown_report_name(std_report)

        if self._NEW_REPORT_NAME in std_report:
            source_report_name = self._NEW_REPORT_NAME
            current_report = std_report.get(self._NEW_REPORT_NAME, {})
        elif old_report_name:
            source_report_name = old_report_name
            current_report = std_report.get(old_report_name, {})
            print(
                "New Belchertown installer: detected existing Belchertown report; "
                "upgrading it to [StdReport][new-belchertown].",
                flush=True,
            )
        else:
            source_report_name = self._NEW_REPORT_NAME
            current_report = {}

        commented_extra_overrides = self._extract_commented_extra_overrides(
            engine,
            current_config,
            (source_report_name,),
        )
        self._normalize_placeholder_keys_in_report(current_report)
        detected_legacy = self._detect_legacy_keys(current_report)
        migrate_legacy = self._should_migrate_legacy_keys(detected_legacy)
        if migrate_legacy:
            self._migrate_legacy_keys_in_report(current_report)

        preserved_legacy_extras = {}
        legacy_insert_before = {}
        legacy_insert_end = []
        if not migrate_legacy and isinstance(current_report, (dict, configobj.Section)):
            extras_section = current_report.get("Extras", {})
            existing_extras = self._section_to_dict(extras_section)
            for legacy_key in self._LEGACY_EXTRAS_MAPPING:
                if legacy_key in existing_extras:
                    preserved_legacy_extras[legacy_key] = (
                        self._normalize_old_belchertown_paths(
                            existing_extras[legacy_key]
                        )
                    )

            default_extras, _ = self._get_skin_defaults()
            legacy_insert_before, legacy_insert_end = (
                self._build_legacy_extras_insert_plan(
                    extras_section,
                    preserved_legacy_extras.keys(),
                    default_extras.keys(),
                    self._LEGACY_EXTRAS_MAPPING,
                )
            )

        preserved_labels = None
        preserved_report_options = {}
        if isinstance(current_report, (dict, configobj.Section)):
            preserved_labels = self._extract_label_overrides(
                current_report.get("Labels")
            )
            preserved_report_options = self._extract_report_overrides(current_report)

        fresh_config = self._build_new_belchertown_template(
            current_report,
            commented_extra_overrides,
            preserved_legacy_extras,
            legacy_insert_before,
            legacy_insert_end,
        )
        if fresh_config is None:
            return False

        self._cleanup_following_report_comments(std_report)
        report_names_to_replace = [self._NEW_REPORT_NAME]
        report_names_to_replace.extend(self._OLD_REPORT_NAMES)
        if old_report_name and old_report_name not in report_names_to_replace:
            report_names_to_replace.append(old_report_name)
        for report_name in report_names_to_replace:
            if report_name in std_report:
                del std_report[report_name]

        current_config.merge(fresh_config)
        report_section = std_report[self._NEW_REPORT_NAME]

        if preserved_report_options:
            if hasattr(report_section, "merge"):
                report_section.merge(preserved_report_options)
            else:
                report_section.update(preserved_report_options)

        if isinstance(preserved_labels, dict) and preserved_labels:
            report_section["Labels"] = preserved_labels
            if not report_section.comments.get("Labels"):
                report_section.comments["Labels"] = [""]

        return True

    def __init__(self):
        super(NewBelchertownInstaller, self).__init__(
            version=VERSION,
            name=NAME,
            description=DESCRIPTION,
            author=AUTHOR,
            author_email=AUTHOR_EMAIL,
            config=config_dict,
            files=files_dict,
        )


# ----------------------------------
#         config stanza
# ----------------------------------

# Keep this bootstrap config intentionally minimal.
# Canonical New Belchertown option defaults live in skins/new-belchertown/skin.conf,
# and configure() rebuilds [[[Extras]]] from that file.
config_dict = NewBelchertownInstaller._build_bootstrap_config()

# ----------------------------------
#        files stanza
# ----------------------------------

files = [
    ("bin/user", ["bin/user/new_belchertown.py"]),
    (
        "skins/new-belchertown",
        [
            "skins/new-belchertown/favicon.ico",
            "skins/new-belchertown/index_radar.inc.example",
            "skins/new-belchertown/footer.html.tmpl",
            "skins/new-belchertown/header.html.tmpl",
            "skins/new-belchertown/index.html.tmpl",
            "skins/new-belchertown/about.inc.example",
            "skins/new-belchertown/kiosk.html.tmpl",
            "skins/new-belchertown/kiosk.css",
            "skins/new-belchertown/celestial.inc",
            "skins/new-belchertown/daylight.inc",
            "skins/new-belchertown/almanac_daylight_data.inc",
            "skins/new-belchertown/charts.conf.example",
            "skins/new-belchertown/page-header.inc",
            "skins/new-belchertown/manifest.json.tmpl",
            "skins/new-belchertown/records.inc.example",
            "skins/new-belchertown/records-table.inc.example",
            "skins/new-belchertown/robots.txt",
            "skins/new-belchertown/skin.conf",
            "skins/new-belchertown/new-belchertown-dark.min.css",
            "skins/new-belchertown/style.css",
        ],
    ),
    ("skins/new-belchertown/about", ["skins/new-belchertown/about/index.html.tmpl"]),
    ("skins/new-belchertown/charts", ["skins/new-belchertown/charts/index.html.tmpl"]),
    (
        "skins/new-belchertown/noaa",
        [
            "skins/new-belchertown/noaa/NOAA-YYYY-MM.txt.tmpl",
            "skins/new-belchertown/noaa/NOAA-YYYY.txt.tmpl",
        ],
    ),
    ("skins/new-belchertown/pi", ["skins/new-belchertown/pi/index.html.tmpl"]),
    (
        "skins/new-belchertown/records",
        [
            "skins/new-belchertown/records/index.html.tmpl",
        ],
    ),
    ("skins/new-belchertown/reports", ["skins/new-belchertown/reports/index.html.tmpl"]),
    (
        "skins/new-belchertown/js",
        [
            "skins/new-belchertown/js/new-belchertown.js.tmpl",
            "skins/new-belchertown/js/new-belchertown-utils.js.tmpl",
            "skins/new-belchertown/js/new-belchertown-forecast.js.tmpl",
            "skins/new-belchertown/js/new-belchertown-mqtt.js.tmpl",
            "skins/new-belchertown/js/new-belchertown-charts.js.tmpl",
            "skins/new-belchertown/js/index.html",
            "skins/new-belchertown/js/responsive-menu.js",
        ],
    ),
    (
        "skins/new-belchertown/json",
        [
            "skins/new-belchertown/json/index.html",
            "skins/new-belchertown/json/weewx_data.json.tmpl",
        ],
    ),
    (
        "skins/new-belchertown/lang",
        [
            "skins/new-belchertown/lang/ca.conf",
            "skins/new-belchertown/lang/da.conf",
            "skins/new-belchertown/lang/de.conf",
            "skins/new-belchertown/lang/es.conf",
            "skins/new-belchertown/lang/fr.conf",
            "skins/new-belchertown/lang/it.conf",
            "skins/new-belchertown/lang/nb.conf",
            "skins/new-belchertown/lang/nl.conf",
            "skins/new-belchertown/lang/pl.conf",
            "skins/new-belchertown/lang/pt.conf",
            "skins/new-belchertown/lang/sv.conf",
        ],
    ),
    (
        "skins/new-belchertown/images",
        [
            "skins/new-belchertown/images/clear-day.png",
            "skins/new-belchertown/images/clear-night.png",
            "skins/new-belchertown/images/cloudy.png",
            "skins/new-belchertown/images/drizzle.png",
            "skins/new-belchertown/images/fog.png",
            "skins/new-belchertown/images/hail.png",
            "skins/new-belchertown/images/mostly-clear-day.png",
            "skins/new-belchertown/images/mostly-clear-night.png",
            "skins/new-belchertown/images/mostly-cloudy-day.png",
            "skins/new-belchertown/images/mostly-cloudy-night.png",
            "skins/new-belchertown/images/partly-cloudy-day.png",
            "skins/new-belchertown/images/partly-cloudy-night.png",
            "skins/new-belchertown/images/rain.png",
            "skins/new-belchertown/images/sleet.png",
            "skins/new-belchertown/images/snow.png",
            "skins/new-belchertown/images/snowflake-icon-15px.png",
            "skins/new-belchertown/images/station.png",
            "skins/new-belchertown/images/station48.png",
            "skins/new-belchertown/images/station72.png",
            "skins/new-belchertown/images/station96.png",
            "skins/new-belchertown/images/station144.png",
            "skins/new-belchertown/images/station168.png",
            "skins/new-belchertown/images/station192.png",
            "skins/new-belchertown/images/sunrise.png",
            "skins/new-belchertown/images/sunset.png",
            "skins/new-belchertown/images/thunderstorm.png",
            "skins/new-belchertown/images/tornado.png",
            "skins/new-belchertown/images/unknown.png",
            "skins/new-belchertown/images/wind.png",
            "skins/new-belchertown/images/windy.png",
            "skins/new-belchertown/images/index.html",
            "skins/new-belchertown/images/aeris-icon-list.json",
        ],
    ),
]
files_dict = files

# ---------------------------------
#          done
# ---------------------------------
