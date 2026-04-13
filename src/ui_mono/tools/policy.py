from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class PolicyVerdict(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class PolicyResult:
    verdict: PolicyVerdict
    reason: str = ""


# 明确拒绝的高危模式（包含任一即拒绝）
_DENIED_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+-[a-z]*r[a-z]*f\b", "destructive recursive file deletion is not allowed"),
    (r"\brm\s+-[a-z]*f[a-z]*r\b", "destructive recursive file deletion is not allowed"),
    (r"\bshutdown\b", "system shutdown commands are not allowed"),
    (r"\breboot\b", "system reboot commands are not allowed"),
    (r"\bmkfs\b", "filesystem formatting commands are not allowed"),
    (r"\bformat\s+[a-z]:", "disk format commands are not allowed"),
    (r"\bgit\s+reset\s+--hard\b", "destructive git reset is not allowed"),
    (r"\bgit\s+clean\s+-[a-z]*[xfd]{2,}", "destructive git clean is not allowed"),
    (r"\bgit\s+push\s+.*--force\b", "force push is not allowed"),
    (r"\bgit\s+push\s+-f\b", "force push is not allowed"),
    (r"del\s+/[sf]", "destructive file deletion is not allowed"),
    (r"rmdir\s+/[sq]", "destructive directory removal is not allowed"),
    (r":\(\)\{:\|:&\};:", "fork bomb commands are not allowed"),
    (r"\bdd\s+.*\bof=/dev/", "direct disk write is not allowed"),
    (r"\bchmod\s+777\b", "world-writable permission change is not allowed"),
    (r"\bcurl\b.*\|\s*(?:bash|sh)\b", "piping curl to shell is not allowed"),
    (r"\bwget\b.*\|\s*(?:bash|sh)\b", "piping wget to shell is not allowed"),
]

# 需要审批的中风险命令（明确允许前需人工确认）
_APPROVAL_PATTERNS: list[tuple[str, str]] = [
    (r"\bgit\s+push\b", "git push affects remote repository — approval required"),
    (r"\bgit\s+merge\b", "git merge may cause conflicts — approval required"),
    (r"\bgit\s+rebase\b", "git rebase rewrites history — approval required"),
    (r"\bgit\s+tag\b", "git tag creates a public ref — approval required"),
    (r"\bpip\s+install\b", "pip install modifies the environment — approval required"),
    (r"\bpip3\s+install\b", "pip install modifies the environment — approval required"),
    (r"\bnpm\s+install\b", "npm install modifies the environment — approval required"),
    (r"\bnpm\s+publish\b", "npm publish affects remote registry — approval required"),
]

# 明确允许的安全命令（优先于审批规则）
_ALLOWED_PREFIXES: list[str] = [
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "py -m pytest",
    # pip install 在 allowed_overrides 前会被 approval 拦截，
    # 若调用者传入 auto_approve=True 则跳过 approval 检查
]

_ALLOWED_PATTERNS: list[str] = [
    r"^\s*\"?[^\s\"]+python[^\s\"]*\"?\s+-m\s+pytest\b",       # "path/to/python" -m pytest
    r"^\s*\"?[^\s\"]+python[^\s\"]*\"?\s+[^\s]+\.py\b",         # python script.py
    r"^\s*\"?[^\s\"]+py\.exe\"?\s+-m\s+pytest\b",               # py.exe -m pytest
    r"^\s*\"?[^\s\"]+py\"?\s+-\d+\.\d+\s+-m\s+pytest\b",       # py -3.13 -m pytest
    r"^\s*git\s+(?:status|log|diff|show|branch|remote|fetch|stash\s+list|ls-files)\b",  # read-only git
    r"^\s*git\s+stash\b(?!\s+pop|\s+drop|\s+clear)",            # git stash (create only)
    r"^\s*git\s+add\b",                                          # git add (staging)
    r"^\s*git\s+commit\b",                                       # git commit
    r"^\s*git\s+checkout\s+-b\b",                                # create new branch
    r"^\s*git\s+switch\b",                                       # switch branch
    r"^\s*git\s+clone\b",                                        # clone
    r"^\s*\"?[^\s\"]+pip[^\s\"]*\"?\s+(?:list|show|freeze|check)\b",   # pip read-only
    r"^\s*\"?[^\s\"]+pip[^\s\"]*\"?\s+install\b",               # pip install (needs approval)
    r"^\s*\"?[^\s\"]+pip3[^\s\"]*\"?\s+install\b",              # pip3 install (needs approval)
    r"^\s*python[^\s]*\s+-c\b",                                  # python -c inline
    r"^\s*\"?[^\s\"]+python[^\s\"]*\"?\s+-c\b",                 # "path/python" -c inline
    r"^\s*echo\b",                                               # echo
    r"^\s*cat\b",                                                # cat
    r"^\s*ls\b",                                                 # ls
    r"^\s*dir\b",                                                # dir (windows)
    r"^\s*pwd\b",                                                # pwd
    r"^\s*which\b",                                              # which
    r"^\s*where\b",                                              # where (windows)
    r"^\s*type\b",                                               # type (windows cat)
    r"^\s*npm\s+(?:test|run\s+\S+|ls|list|outdated|audit)\b",   # npm safe ops
    r"^\s*cargo\s+(?:test|build|check|clippy|fmt|doc)\b",        # cargo
    r"^\s*go\s+(?:test|build|vet|fmt|doc)\b",                   # go
    r"^\s*mvn\s+(?:test|compile|package|verify)\b",              # maven
    r"^\s*gradle\s+(?:test|build|check)\b",                     # gradle
]


@dataclass
class ShellCommandPolicy:
    """集中式 shell 命令策略。

    verdict 说明：
    - ALLOW            — 直接执行
    - DENY             — 立即拒绝，抛 PermissionError
    - REQUIRE_APPROVAL — 需人工确认；非交互模式下可等同 DENY
    """

    auto_approve: bool = False  # True = headless 模式跳过 approval 检查，直接拒绝

    def check(self, command: str) -> PolicyResult:
        normalized = " ".join(command.strip().lower().split())

        # 1. 先检查高危拒绝规则（最高优先级）
        for pattern, reason in _DENIED_PATTERNS:
            if re.search(pattern, normalized):
                return PolicyResult(PolicyVerdict.DENY, reason)

        # 2. 检查是否匹配允许模式（优先于审批规则）
        for pattern in _ALLOWED_PATTERNS:
            if re.search(pattern, normalized):
                # 仍需经过 approval 规则（pip install 被允许但需审批）
                for ap_pattern, ap_reason in _APPROVAL_PATTERNS:
                    if re.search(ap_pattern, normalized):
                        if self.auto_approve:
                            return PolicyResult(PolicyVerdict.DENY, f"{ap_reason} (auto-denied in non-interactive mode)")
                        return PolicyResult(PolicyVerdict.REQUIRE_APPROVAL, ap_reason)
                return PolicyResult(PolicyVerdict.ALLOW)

        # 3. 检查需要审批的规则（未被 allowed 覆盖的中风险命令）
        for pattern, reason in _APPROVAL_PATTERNS:
            if re.search(pattern, normalized):
                if self.auto_approve:
                    return PolicyResult(PolicyVerdict.DENY, f"{reason} (auto-denied in non-interactive mode)")
                return PolicyResult(PolicyVerdict.REQUIRE_APPROVAL, reason)

        # 4. 默认拒绝（未在白名单内的命令一律不执行）
        return PolicyResult(PolicyVerdict.DENY, "command is not in the allowed list; only whitelisted commands are permitted")

    def validate(self, command: str) -> None:
        """向后兼容接口：ALLOW 直接返回，否则抛 PermissionError。"""
        result = self.check(command)
        if result.verdict == PolicyVerdict.ALLOW:
            return
        raise PermissionError(f"blocked by shell policy: {result.reason}")


default_shell_command_policy = ShellCommandPolicy(auto_approve=True)
