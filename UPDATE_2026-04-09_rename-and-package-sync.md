# 更新记录（2026-04-09）

## 本次目标
- 将项目从 `py-coding-agent` 全量重命名为 `py-pi-agent`
- 收尾清理重命名残留，保证包名、入口与元数据一致
- 为后续 GitHub 推送做准备

## 已完成变更
1. 项目与包命名一致化
   - 项目名：`py-coding-agent` -> `py-pi-agent`
   - 包名：`py_coding_agent` -> `py_pi_agent`

2. 关键配置同步
   - `pyproject.toml`：`project.name` 与 `project.scripts` 已切换为新名称
   - `README.md` 标题已切换为 `py-pi-agent`
   - `src/py_pi_agent/config.py` 中 agent home 路径改为 `~/.py-pi-agent`

3. 代码与测试 import 链路修正
   - `src/py_pi_agent/` 下模块 import 全部统一到 `py_pi_agent`
   - `tests/` 下测试 import 全部统一到 `py_pi_agent`

4. egg-info 残留清理
   - `src/py_coding_agent.egg-info` 已更新内容并重命名为 `src/py_pi_agent.egg-info`
   - `PKG-INFO`、`entry_points.txt`、`top_level.txt`、`SOURCES.txt` 已与新命名对齐
   - 全项目检索确认不再存在旧名称残留（`py-coding-agent` / `py_coding_agent`）

## 验证结果
- 之前已完成 `pytest` 回归（9 passed，使用 `PYTHONPATH=.../src`）
- 本次收尾后再次做全局检索，未发现旧命名残留

## 待执行
- 初始化 Git 仓库并配置远端
- 提交当前改动并推送到 GitHub
- 后续每次更新继续新增一份同类 md 记录
