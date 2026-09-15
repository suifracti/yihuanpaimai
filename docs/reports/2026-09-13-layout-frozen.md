# 自适应布局冻结及编辑复验

干净ac3cac3隔离包已纳入085b498布局修复。最新候选build/isolated_trial_layout_20260913/dist/异环拍卖助手，metadata ac3cac3/isDirty=false。

同EXE实际双窗口：frozen默认/全展开/关闭分区/收起72px四阶段高度、底部可达和hidden不可见PASS；已查看expanded.png确认深色输入、完整布局和恢复按钮隐藏。frozen-edit复验17项数值Main→HUD、HUD修改/0/清空→Main，PASS。frozen-constrained新增原生窗口直接缩到600×480，面板scrollHeight超过clientHeight、scroll到底最后元素完整可见且无横向越界，关闭分区恢复自然高度及收起72px，PASS。报告build/hud_layout_20260913/{frozen,frozen-edit,frozen-constrained}/report.json；真实原生窗口尺寸，非实际小屏设备/全DPI/鼠标滚轮验收。

日常历史SHA256保持19100479bbb2dfd8e09faa2adbaf5117919126df4b4bcf92e377ad88c4da3431。未覆盖v13。本轮验证工具新增小窗口检查，未再改业务代码。

下一步继续其余词条语义及完整试用流程核对。P3 PARTIAL、P4实施中、完整试用/P5未完成；逐件匹配调优暂停，未执行真实70秒游戏输入。历史其他回归不自动扩为本候选全项通过。
