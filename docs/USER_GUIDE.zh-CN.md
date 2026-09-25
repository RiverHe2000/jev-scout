# Jev Scout 使用与展示指南

Jev Scout 是围绕研究问题筛选论文的本地工具。它把论文放进“优先读、略读、需要复核、以后再读”四类，并展示模型选择的摘要原句，帮助你决定下一步读什么。

## 在这台电脑上打开

项目目录是 `D:\Project\jev-scout`。启动后访问 <http://127.0.0.1:8765>。

```powershell
cd D:\Project\jev-scout
.\scripts\start_local.ps1
```

首次安装或在另一台电脑上使用，请先按 [安装说明](INSTALLATION.md) 准备环境。`scripts\bootstrap.ps1 -Dev` 会安装固定版本的开发依赖并构建页面。

不配置 API 时可以使用离线关键词模式。连接 OpenRouter 的 Jev，只需将密钥写入项目 `.env` 的 `OPENROUTER_API_KEY`，然后重启。密钥不要写进页面、截图或 GitHub。README 中有完整配置示例。

如果已经把 `OPENROUTER_API_KEY` 配置为 Windows 用户环境变量，启动脚本也会在当前终端尚未加载它时读取该变量，不需要再复制到 `.env`。界面的“Configured”表示已读取配置；真正启动分析后才能验证服务是否可用。

这台电脑已有 Qwen 权重及 GPU 环境时，可这样启动真实本地模型：

```powershell
.\scripts\start_local.ps1 -WithLocalModel `
  -ModelPath 'D:\models\Qwen3-4B-Instruct-2507' `
  -ModelPython 'D:\Project\.venv\Scripts\python.exe'
```

如果已经运行，先执行 `scripts\stop_local.ps1`，再以需要的模式启动。此命令只管理启动脚本记录的项目进程，不会停止其他 Python 程序。

## 第一次使用

1. 在 **Research profiles** 创建研究问题。问题越具体，判断越有意义，例如“哪些方法能改善多轮对话中跨会话记忆的可靠性？”
2. 添加最多三项偏好及权重，例如是否报告记忆失效分析。关键词用于离线对照，不能代替语义判断。种子论文是记录研究背景的参考，不会自动训练模型。
3. 在 **Import papers** 粘贴 arXiv 链接或输入 arXiv 查询。选择分析方法后，后台任务开始导入和判断。
4. 打开一篇论文，查看 **Evidence** 中的摘要原句。判断依据来自摘要，不代表已验证全文实验。
5. 收藏论文，在 **Your notes** 写笔记，用阅读进度和反馈记录自己的决定。反馈只保存到当前研究档案，不会暗中修改偏好。
6. 在 **Export** 导出 BibTeX、Markdown 或 JSON。BibTeX 可供 Zotero/LaTeX 使用。

修改研究问题后，旧判断会标记为需要复核；点击 **Run analysis** 重新分析。**Activity & insights** 显示任务、真实用量和基准测试状态。

## 面试展示顺序

建议用三分钟演示：研究问题 → 同一篇论文在不同问题下的判断 → 摘要证据 → 修改偏好后的版本变化 → 收藏与导出。再打开活动页，解释调用成本、失败记录和质量评测边界。

可以描述你实现了可追踪的论文筛选系统、多模型适配、版本化缓存、任务恢复和原文证据。没有人工标注时，不要声称“准确率提升了多少”或“节省了多少阅读时间”。项目提供了评测流程，待你按协议补上独立人工标注后才有资格填这些指标。可参考 [面试说明](INTERVIEW.md) 和 [实际验证记录](RESULTS.md)。

## GitHub 发布前

代码已经按本地项目组织，你自行创建仓库并推送。`.env`、运行数据库、依赖目录和构建产物均应保持忽略。公开截图只展示示例研究内容；自己的私人笔记不要随数据库上传。

工作流会在你推送后运行检查。目前本机验证与未来 GitHub CI 状态是两回事。容器说明也明确区分了配置完成和实际运行验证。
