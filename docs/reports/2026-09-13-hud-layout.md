# 悬浮窗布局与可访问性

085b498修固定展开高度340/378导致新增表单裁切：按可见直接子元素自然高度计算，限制screen.availHeight-80；展开面板flex+overflow-y:auto，子元素不压缩。分区关闭重新计算自然高度，避免scrollHeight受当前视口撑大后无法缩回。新增数值框改为深色、字号/间距与现有样式一致；[hidden]强制隐藏，修恢复按钮被通用按钮display覆盖的问题。

源码真实双窗口布局检查final PASS：默认展开、全展开、关闭所有分区、整体折叠四阶段高度匹配，全部展开高于默认，关闭分区恢复默认高度，折叠72px；滚到底最后子元素在视口内且无横向越界；所有hidden元素无可见矩形。工具tools/verify_hud_layout_ui.py。截图build/hud_layout_20260913/{source,styled,final}/expanded.png，已人工视觉检查source和styled发现并调整白底输入/隐藏按钮问题；final DOM断言验证隐藏修复。不是所有DPI/屏幕尺寸或真实鼠标滚轮验收。

源码尚未冻结，最新候选仍052dbb9（旧固定高度问题尚在）。下一步统一冻结布局与编辑回归，再继续剩余词条及试用流程。P3 PARTIAL、P4实施中、完整试用/P5未完成；逐件匹配调优暂停、v13未覆盖。
