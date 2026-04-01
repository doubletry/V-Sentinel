# 工程优化路线图

本文档记录当前 V-Sentinel 仓库按收益排序的工程优化项，并标注本轮已经落地的部分，方便后续继续推进。

## 已完成

### 1. 前端路由按需加载与基础拆包

- 状态：已完成
- 落地点：
  - `frontend/src/router/index.js`
  - `frontend/vite.config.js`
- 本轮动作：
  - 将页面路由改为动态导入，避免所有页面进入首屏包
  - 将 Element Plus 从整包安装改为按需组件注册，并仅注册实际使用的图标
  - 为 Vue、UI 依赖、Axios 等增加基础 `manualChunks`
- 预期收益：
  - 降低首屏 JS 体积
  - 加快首次加载速度
  - 为后续页面继续增加功能预留包体空间

### 2. SQLite 共享连接与 WAL 模式

- 状态：已完成
- 落地点：
  - `backend/db/database.py`
  - `backend/main.py`
  - `tests/conftest.py`
- 本轮动作：
  - 增加共享 SQLite 连接复用，避免每次 DB 操作重新 `connect`
  - 打开 `journal_mode=WAL`
  - 配置 `foreign_keys=ON`、`synchronous=NORMAL`、`busy_timeout=5000`
  - 在应用关闭与测试结束时显式关闭共享连接
- 预期收益：
  - 降低数据库连接开销
  - 提升并发读写稳定性
  - 减少多摄像头场景下的数据库争用问题

## 待继续推进

### 3. ProcessorManager 批量启停改为并发

- 收益等级：高
- 关键位置：`backend/processing/manager.py`
- 当前问题：`start_all_processors()` / `stop_all_processors()` 仍按 source 串行执行
- 预期收益：多路摄像头启停时间从线性叠加下降到接近单路启动耗时

### 4. 配置与 ROI 输入校验增强

- 收益等级：高
- 关键位置：`backend/models/schemas.py`
- 当前问题：
  - `processor_plugin` 仍是任意字符串
  - ROI 坐标没有严格限制在 `[0, 1]`
- 预期收益：在请求入口拦截坏配置，减少运行期异常

### 5. gRPC 客户端热重连与失败恢复增强

- 收益等级：高
- 关键位置：`core/vengine_client.py`
- 当前问题：
  - 热重连策略偏直接
  - 短时错误缺少更清晰的恢复/重试策略
- 预期收益：提高 V-Engine 波动场景下的可用性

### 6. 处理链背压与可观测性增强

- 收益等级：中高
- 关键位置：`core/base_processor.py`
- 当前问题：
  - 队列丢帧与 inflight 控制已有，但缺少配套指标
  - 现场问题较难快速判断是 RTSP、推理还是推流瓶颈
- 预期收益：提升线上调参与排障效率

### 7. 前端消息缓存进一步优化

- 收益等级：中
- 关键位置：`frontend/src/stores/message.js`
- 当前问题：当前仍为固定长度数组缓存，长时间运行时仍会有一定内存与渲染成本
- 预期收益：降低监控大屏长时间驻留时的前端资源占用

### 8. 前端自动化测试补齐

- 收益等级：中
- 关键位置：`frontend/package.json` 及前端 stores/views`
- 当前问题：当前主要依赖构建验证，缺少设置页、消息流、路由加载等自动化测试
- 预期收益：降低后续交互改动的回归成本

## 推荐下一步顺序

1. 并发化 ProcessorManager 批量启停
2. 强化 `processor_plugin` 与 ROI 输入校验
3. 改善 gRPC 客户端的失败恢复
4. 增加前端测试基座（Vitest）