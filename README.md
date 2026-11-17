# 并行学习与补课流程服务

办理台账按明确实例展示原始时间线，并单独保留未归属事件、暂停记录与校区观察窗口。

## 运行环境

使用 Python 3.11，仅依赖标准库，无外部服务、账号或网络数据。
示例数据使用虚构标识和本地合成记录，不涉及真实学员。

```bash
python3 -m app check
python3 -m app summary
python3 -m app serve --host 127.0.0.1 --port 8080
```

服务提供只读 JSON 查询：`/api/timelines`, `/api/states`，以及学习办理过程分析
`/api/process/instances`, `/api/process/stages`, `/api/process/campuses`, `/api/process/findings`, `/api/process/plan`。
`/health` 显示存活及表计数，`/api/records?table=表名` 可查看已知数据表。
详细字段语义、计数单位和当前能力见 `docs/数据契约.md`。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q app tests smoke.py
python3 smoke.py
```

测试从实际数据装载进入领域计算、报告与真实 HTTP 服务，并用临时副本验证错误输入。
冒烟程序动态分配本地端口，启动服务后读取全部业务查询并原样输出 JSON，随后正常关闭。
查询不写回数据，因此可以直接重复运行；验证不会访问项目外文件。

## 容器

```bash
docker build -t learning-journeys:local .
docker run --rm --network none learning-journeys:local
docker run --rm --network none learning-journeys:local python3 smoke.py
```

镜像只封装本应用，测试使用回环网络，不依赖宿主端口。
无第三方包依赖，`requirements.lock` 记录此状态。

## 业务办理

过程分析从明确归属的事件计算环节耗时：区分并行活动、重复办理、主动暂停与真正卡住（stuck）的环节；未归属事件只列候选不自动配对；day 精度记录只产生整天粒度；未结束流程按校区观察窗口计删失等待，不当作失败。findings 给出带证据的卡点与负责人，plan 在协助名额内给出优先顺序，未覆盖实例标记 unresolved。

人工以明确实例开协调单（可附 evidence；同一材料不重复开冲突单），events.reassign 人工纠正误配事件并释放原负责人名额，assistance.allocate 分配校区协助名额，notices.send 在名额确认后发告知并记录当时依据（basis）；暂停或等待不确定的实例不催促。

业务操作以 JSON 对象 POST 到 `/api/workflow/操作名`，下列操作保留现有函数入参和行为。

- `coordination.open_case`
- `assistance.allocate`
- `events.reassign`
- `notices.send`

业务贯通用例见 `tests/test_workflows.py`，其中为可直接运行的本地调用。默认状态存于内存；需要重启后保留时，可运行 `python3 -m app serve --state /tmp/learning-service.sqlite3`。状态库只保留本机操作，不向外部发送数据。
