from __future__ import annotations

from pathlib import Path
import json

from typer.testing import CliRunner

from ui_mono.cli import app



def test_code_demo_command_runs_coding_loop(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["code-demo", "--cwd", str(tmp_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["result"]["pytest_passed"] is True
    assert len(payload["result"]["bash_runs"]) == 2
    assert "Command exited with code 1" in payload["result"]["bash_runs"][0]["content"]
    assert "1 passed" in payload["result"]["bash_runs"][1]["content"]
    assert "return a + b" in Path(payload["inspect"]["source_file"]).read_text(encoding="utf-8")
    assert payload["inspect"]["reply"]



def test_code_demo_command_supports_text_output(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["code-demo", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert '"pytest_passed": true' in result.output.lower()
    assert "source_file" in result.output



def test_code_demo_command_supports_json_stream(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["code-demo", "--cwd", str(tmp_path), "--json-stream"])

    assert result.exit_code == 0
    lines = [json.loads(line) for line in result.output.splitlines() if line.strip().startswith("{")]
    bash_ends = [
        line
        for line in lines
        if line["event"] == "tool_execution_end" and line["payload"]["tool"]["name"] == "bash"
    ]
    assert len(bash_ends) == 2
    assert "Command exited with code 1" in bash_ends[0]["payload"]["result"]["content"]
    assert "1 passed" in bash_ends[1]["payload"]["result"]["content"]
    assert any(line["event"] == "turn_end" and line["payload"]["turn"]["reply"] for line in lines)
