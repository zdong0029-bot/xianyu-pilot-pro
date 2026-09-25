# 商机监控、热榜和比价测试

这部分功能已经接入原有的用户端「商机发现」页、Java 网关、Python 自动化服务及后台 worker。原项目的多账号、自动回复、发货和上架等入口保留。

## 启动与验收

1. 按项目根目录 README 配置 `.env`，执行 `docker compose up -d --build`。本地默认开启的 `SchemaCompatibilityRunner` 会幂等创建 `market_watch`、`market_snapshot` 和 `market_price_quote` 表。若把 `SCHEMA_RUNTIME_MUTATIONS_ENABLED` 设为 `false`，应在服务启动前由 DBA 按迁移清单执行 `V1.76__market_intelligence.sql`；不要在生产环境开启运行时建表。
2. 打开 `http://localhost:5174`，登录后先在「账号管理」扫码登录一个闲鱼账号。
3. 进入「商机发现」→「近期商品热榜」，选账号、输入关键词、添加监控，点「立即采集」。首次采集建立基线；间隔 30 分钟以上再次采集后，热榜按已知的浏览、想要、已售增量排序。平台未提供的指标显示「未知」，不会按 0 计算。
4. 在热榜商品上点「比价」，填入真实的拼多多或 1688 同款链接、规格证据、单价、运费和起订量。价差按运费分摊后的单件成本计算。报价明确标记为「人工录入」。拼多多和 1688 的自动报价需要后续接入合法的数据接口凭据，目前不会伪装成自动抓到的价格。

## 压力测试顺序

先压本地只读热榜接口，不要并发触发闲鱼采集。已有监控任务 ID 后，在本机设置 `MARKET_TEST_TOKEN` 为用户端登录令牌，再运行：

```bash
python scripts/market_read_load.py --base-url http://localhost:18080 --watch-id 1 --requests 100 --concurrency 10
```

脚本只接受 `localhost` / `127.0.0.1`，仅请求 `GET /api/market/trends`，输出成功数、平均、P95、最大耗时；不会对闲鱼或第三方平台施压。逐级增加到 500/20、1000/30，观察 `backend`、`automation`、`mysql`、`automation-worker` 的 CPU、内存和错误日志。定时采集本身按任务间隔运行、每轮最多取 3 个任务，并用数据库锁防止重复领取。

## 已知边界

- 排名是指定关键词、指定已登录账号可见的商品样本，不是闲鱼全站热销榜。
- 每次采集第一页最多 50 件商品；查询最多读取最近 5000 条快照，响应中的 `truncated=true` 表示窗口数据被截断，不能把结果当完整排行。
- 仅有一次采样或平台没有提供互动指标时，热度显示「待积累」。
- 当前环境没有 Docker，因此交付前只能做代码级校验；实际容器启动和容量测试需在有 Docker 的测试机进行。
