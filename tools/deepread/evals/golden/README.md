# deepread 的金标集

**这里目前是空的，而且大概率会一直空着 —— 这是有意的。**

精读的金标不是我们造的样例，而是**用户对真实精读的好/差评价**：
他在 Zotero 打「读完」标签，在控制面板的「精读评价」卡片里评一句好或差。
那份数据存在 `workflow_data/evalset.json`（R6 窗后是 `data/state/evalset.json`），
**不可重建**，所以它跟着数据走、并且被版本库保护
（`tests/test_architecture.py::test_用户不可重建的数据仍在版本库里` 在守它）。

放进这个目录的应该是**另一类东西**：将来若要固定几篇「已知好」和「已知差」的
精读 HTML 用来回归测试评分器（改了 `scorers/quality.py` 之后指标不该乱跳），
那几份 HTML 放这里。目前评分器的回归靠 `tests/test_evals.py` 里的合成样例。
