import json
import re


def extract_json(content):
    """Extract a JSON object from LLM output, handling common issues.

    Handles: markdown code fences, trailing text after JSON,
    unescaped control characters in string values.
    Returns parsed dict/list or None on failure.
    """
    if not content or not content.strip():
        return None

    content = content.strip()

    # Strip markdown code fences
    if content.startswith("```"):
        content = re.sub(r'^```\w*\n?', '', content)
        content = re.sub(r'\n?```$', '', content)
        content = content.strip()

    # Try direct parse first (fastest path)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try raw_decode to extract first JSON object (handles trailing text)
    try:
        decoder = json.JSONDecoder()
        result, _ = decoder.raw_decode(content)
        return result
    except json.JSONDecodeError:
        pass

    # Try escaping control chars in string values, then parse
    try:
        escaped = _escape_string_values(content)
        return json.loads(escaped)
    except json.JSONDecodeError:
        pass

    # Try escaping + raw_decode
    try:
        escaped = _escape_string_values(content)
        decoder = json.JSONDecoder()
        result, _ = decoder.raw_decode(escaped)
        return result
    except json.JSONDecodeError:
        pass

    return None


def _escape_string_values(s):
    """Escape control chars inside JSON string values only."""
    out = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ch == '\n':
            out.append('\\n')
        elif in_string and ch == '\r':
            out.append('\\r')
        elif in_string and ch == '\t':
            out.append('\\t')
        else:
            out.append(ch)
    return ''.join(out)
