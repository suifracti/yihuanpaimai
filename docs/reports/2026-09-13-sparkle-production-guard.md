# 闪耀之心生产概率限制

e44836a修旧solver_core有sparkle推荐抑制但当前生产auction_engine/live_shadow_compute没有接通的问题。复现：已知算力面包/金均60040、sparkle、空历史仍生成full_shadow P50与建议价。当前共享生产入口在此词条下提前返回fallback，不构造概率profile或supportCaptureEnvelope；直接solveAuctionPipeline同样抑制整仓分位及推荐线，避免旁路。HUD说明宝石概率待确认；Main保留具体原因。修旧快照Number(null)导致estimate=0，未知保留null。

8项回归PASS（5.422秒），覆盖sparkle/中文/别名、直接引擎及生产Node、无概率profile/捕获包/分位/推荐线，保留原面积回归。先前测试把quantiles=null误当字典，修测试后又发现estimate=0并修业务，失败均保留。build/sparkle_guard_20260913/verified.json。

源码真实UI standard→sparkle→standard通过：词条实际点击、生产valid/fallback/valid、候选释放/恢复，HUD概率待确认与Main无分位；build/sparkle_guard_20260913/ui/report.json（该UI运行在estimate空值修复前，最终空值由后续运行时回归证明）。不是闪耀之心完整支持：已确认转换数量/宝石证据的非概率上下界还未接当前新UI/生产链，继续保留缺口。

源码未入包，最新候选仍ac3cac3且仍存在旧sparkle推荐风险。下一步统一冻结限制复验，再补非概率证据边界及其他词条语义。P3 PARTIAL、P4实施中、完整试用/P5未完成，逐件匹配调优暂停、v13未覆盖。
