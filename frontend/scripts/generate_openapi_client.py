#!/usr/bin/env python3
import json
import os
import re
import urllib.request
from pathlib import Path

OPENAPI_URL = os.getenv("OPENAPI_URL", "http://localhost:8000/openapi.json")
OUT = Path("src/ts/generated/openapiClient.ts")


def to_camel(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name)
    clean = [p for p in parts if p]
    if not clean:
        return "unnamedOperation"
    return clean[0].lower() + "".join(p.capitalize() for p in clean[1:])


def op_name(method: str, path: str, operation_id: str | None) -> str:
    if operation_id:
        return to_camel(operation_id)
    synthesized = f"{method}_{path}".replace("{", "").replace("}", "")
    return to_camel(synthesized)


def read_openapi(url: str) -> dict:
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode("utf-8"))


def generate(spec: dict) -> str:
    paths = spec.get("paths", {})
    functions = []

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "patch", "put", "delete"}:
                continue
            name = op_name(method, path, operation.get("operationId"))
            fn = f"""
export async function {name}(args: {{
  baseUrl?: string;
  pathParams?: Record<string, string | number>;
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
}} = {{}}) {{
  const baseUrl = args.baseUrl ?? "";
  let urlPath = "{path}";
  for (const [key, value] of Object.entries(args.pathParams ?? {{}})) {{
    urlPath = urlPath.replace(`{{${{key}}}}`, encodeURIComponent(String(value)));
  }}

  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(args.query ?? {{}})) {{
    if (value !== undefined) {{
      query.set(key, String(value));
    }}
  }}

  const queryString = query.toString();
  const url = `${{baseUrl}}${{urlPath}}${{queryString ? `?${{queryString}}` : ""}}`;

  const response = await fetch(url, {{
    method: "{method.upper()}",
    credentials: "include",
    headers: {{
      "Content-Type": "application/json",
      ...(args.headers ?? {{}}),
    }},
    body: args.body ? JSON.stringify(args.body) : undefined,
  }});

  if (!response.ok) {{
    throw new Error(`{method.upper()} {path} failed with status ${{response.status}}`);
  }}

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {{
    return response.json();
  }}
  return response.text();
}}
"""
            functions.append(fn.strip("\n"))

    header = """/* eslint-disable */
/* AUTO-GENERATED FILE. DO NOT EDIT DIRECTLY. */
"""
    return header + "\n\n" + "\n\n".join(functions) + "\n"


def main() -> None:
    spec = read_openapi(OPENAPI_URL)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(generate(spec), encoding="utf-8")
    print(f"Generated {OUT} from {OPENAPI_URL}")


if __name__ == "__main__":
    main()
