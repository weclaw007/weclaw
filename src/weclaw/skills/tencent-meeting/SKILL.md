---
name: tencent-meeting
description: 腾讯会议服务，支持会议创建/修改/取消/查询、参会成员管理、录制与转写、智能纪要等功能。使用 weclaw.agent.mcp_client 模块调用。
homepage: https://mcp.meeting.tencent.com/mcp/wemeet-open/v1
metadata:
  {
    "openclaw":
      {
        "emoji": "📋",
        "primaryEnv": "TENCENT_MEETING_TOKEN",
        "requires": { "bins": ["python"] }
      },
  }
---

# 腾讯会议

腾讯会议 MCP 服务，提供会议全生命周期管理功能。通过 `python -m weclaw.agent.mcp_client` 调用远程服务。

## Supported Commands

### 会议管理

### 1. `schedule_meeting` - 创建/预订会议
创建一个新的腾讯会议。
- **subject** (string, 必填): 会议主题
- **start_time** (string, 必填): 会议开始时间，秒级时间戳
- **end_time** (string, 必填): 会议结束时间，秒级时间戳
- **password** (string, 可选): 会议密码（4~6位数字）
- **time_zone** (string, 可选): 时区，遵循 Oracle-TimeZone 标准，例如：Asia/Shanghai
- **meeting_type** (number, 可选): 0：普通会议；1：周期性会议，默认为0
- **only_user_join_type** (number, 可选): 1：所有成员可入会；2：仅受邀成员可入会；3：仅企业内部成员可入会
- **auto_in_waiting_room** (boolean, 可选): true：开启等候室；false：不开启，默认 false
- **recurring_rule** (object, 可选): 周期性会议配置，当 meeting_type=1 时使用
  - **recurring_type** (number): 周期类型：0-每天、1-周一至周五、2-每周、3-每两周、4-每月
  - **until_type** (number): 结束类型：0-按日期结束、1-按次数结束
  - **until_count** (number): 重复次数（1-50次），当 until_type=1 时必填
  - **until_date** (number): 结束日期时间戳（秒级），当 until_type=0 时必填

### 2. `update_meeting` - 修改会议
修改已创建的会议信息（主题、时间、密码、时区、会议类型、入会限制、等候室、周期性规则等）。
- **meeting_id** (string, 必填): 会议ID
- **subject** (string, 可选): 新会议主题
- **start_time** (string, 可选): 新开始时间，秒级时间戳
- **end_time** (string, 可选): 新结束时间，秒级时间戳
- **password** (string, 可选): 会议密码（4~6位数字），设为空字符串 "" 表示取消密码
- **time_zone** (string, 可选): 时区，遵循 Oracle-TimeZone 标准
- **meeting_type** (number, 可选): 0：普通会议；1：周期性会议
- **only_user_join_type** (number, 可选): 成员入会限制（1/2/3）
- **auto_in_waiting_room** (boolean, 可选): 是否开启等候室
- **recurring_rule** (object, 可选): 周期性会议配置
  - **recurring_type** (number): 周期类型：0-每天、1-周一至周五、2-每周、3-每两周、4-每月、5-自定义
  - **until_type** (number): 结束类型：0-按日期结束、1-按次数结束
  - **until_count** (number): 重复次数（1-50次）
  - **until_date** (number): 结束日期时间戳（秒级）
  - **sub_meeting_id** (string): 子会议 ID，修改该子会议时间，不可与周期性会议规则同时修改

### 3. `cancel_meeting` - 取消会议
取消已创建的会议。支持取消普通会议或周期性会议的某个子会议。
- **meeting_id** (string, 必填): 会议ID
- **sub_meeting_id** (string, 可选): 周期性会议子会议ID，取消某个子会议时传入
- **meeting_type** (number, 可选): 取消整场周期性会议时传1，其他情况不传

### 4. `get_meeting` - 查询会议详情
根据会议ID查询会议的详细信息。
- **meeting_id** (string, 必填): 会议ID

### 5. `get_meeting_by_code` - 通过会议Code查询
通过9位会议号查询会议信息。
- **meeting_code** (string, 必填): 9位会议号

### 成员管理

### 6. `get_meeting_participants` - 获取参会成员明细
查询会议的实际参会成员信息。
- **meeting_id** (string, 必填): 会议ID
- **sub_meeting_id** (string, 可选): 周期性会议子会议 ID，周期性会议时必传
- **pos** (string, 可选): 分页查询起始位置，默认为0
- **size** (string, 可选): 每页条数，最大100
- **start_time** (string, 可选): 参会时间过滤起始时间（秒级时间戳）
- **end_time** (string, 可选): 参会时间过滤终止时间（秒级时间戳）

### 7. `get_meeting_invitees` - 获取受邀成员列表
查询会议邀请的成员列表。
- **meeting_id** (string, 必填): 会议ID
- **page_size** (number, 可选): 每页数量，默认20
- **page_number** (number, 可选): 页码，从1开始

### 8. `get_waiting_room` - 查询等候室成员记录
查询会议等候室的成员记录。
- **meeting_id** (string, 必填): 会议ID
- **page_size** (number, 可选): 每页数量，默认20
- **page** (number, 可选): 页码，从1开始

### 9. `get_user_meetings` - 查询用户会议列表
查询当前用户的会议列表。
- **pos** (number, 可选): 查询起始位置，unix 秒级时间戳，默认为0
- **cursory** (number, 可选): 分页游标，默认为20
- **is_show_all_sub_meetings** (number, 可选): 是否展示全部子会议，0-不展示，1-展示，默认为0

### 10. `get_user_ended_meetings` - 查询用户已结束会议列表
查询当前用户在指定时间范围内已结束的会议列表。
- **start_time** (string, 必填): 查询开始时间，秒级时间戳
- **end_time** (string, 必填): 查询结束时间，秒级时间戳
- **page_size** (number, 可选): 每页数量，默认20
- **page_number** (number, 可选): 页码，从1开始

### 录制与转写

### 11. `get_records_list` - 查询录制列表
根据时间范围和会议ID查询用户的录制列表。
- **start_time** (string, 必填): 查询开始时间，秒级时间戳
- **end_time** (string, 必填): 查询结束时间，秒级时间戳
- **page_number** (number, 可选): 页码，从1开始
- **meeting_id** (string, 可选): 会议ID，不为空时优先根据会议ID查询

### 12. `get_record_addresses` - 获取录制下载地址
获取录制文件的下载链接。
- **meeting_record_id** (string, 必填): 会议录制ID
- **page_number** (number, 可选): 页码，从1开始

### 13. `get_transcripts_details` - 查询转写详情
获取录制文件的完整转写内容。
- **record_file_id** (string, 必填): 录制文件ID
- **meeting_id** (string, 可选): 会议ID（传入可加速定位）
- **pid** (string, 可选): 查询的起始段落 ID，默认从0开始
- **limit** (string, 可选): 查询的段落数，默认查询全量数据

### 14. `get_transcripts_paragraphs` - 查询转写段落
分页获取录制文件的转写段落信息（返回段落 ID 列表，配合 `get_transcripts_details` 获取具体文本）。
- **record_file_id** (string, 必填): 录制文件ID
- **meeting_id** (string, 可选): 会议ID

### 15. `search_transcripts` - 搜索转写内容
在录制转写内容中搜索特定关键词。
- **record_file_id** (string, 必填): 录制文件ID
- **text** (string, 必填): 搜索的文本（中文需 urlencode）
- **meeting_id** (string, 可选): 会议ID

### 16. `get_smart_minutes` - 获取智能纪要
获取会议录制的 AI 智能纪要总结。
- **record_file_id** (string, 必填): 录制文件ID
- **lang** (string, 可选): 翻译语言：default(原文)/zh(简体中文)/en(英文)/ja(日语)，默认 default
- **pwd** (string, 可选): 录制文件访问密码（有密码时需传入）

### 17. `export_asr_details` - 导出会议实时转写记录
导出指定条件下的会议实时转写记录。
- **meeting_id** (string, 可选): 会议ID
- **start_time** (string, 可选): 查询开始时间，秒级时间戳
- **end_time** (string, 可选): 查询结束时间，秒级时间戳
- **show_bilingual** (number, 可选): 0：不展示双语转写；1：展示双语转写，默认为0
- **page** (number, 可选): 页码，从1开始

## Quick Start

Python command compatibility (some machines use `python`, others use `python3`):

```bash
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
```

调用工具示例（以创建会议为例）：

> **重要：`-u` 和 `-k` 是固定参数，每次调用都必须原样传递，不可省略、不可修改。直接复制以下示例中的 `-u` 和 `-k` 值即可。**
>
> **本服务需要通过 `-H` 传入自定义 HTTP 头进行认证（每个 header 需单独 `-H` 指定）。**
>
> **参数格式：`-a` 使用 JSON 格式传入参数，如 `-a '{"subject": "产品周会"}'`。**

```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://mcp.meeting.tencent.com/mcp/wemeet-open/v1 \
  -k TENCENT_MEETING_TOKEN \
  -H 'X-Tencent-Meeting-Token=$TENCENT_MEETING_TOKEN' \
  -H 'X-Skill-Version=v1.0.1' \
  call_command schedule_meeting -a '{"subject": "产品周会", "start_time": "1773280800", "end_time": "1773284400"}'
```

### 更多调用示例

#### 查询用户会议列表
```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://mcp.meeting.tencent.com/mcp/wemeet-open/v1 \
  -k TENCENT_MEETING_TOKEN \
  -H 'X-Tencent-Meeting-Token=$TENCENT_MEETING_TOKEN' \
  -H 'X-Skill-Version=v1.0.1' \
  call_command get_user_meetings
```

#### 查询会议详情
```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://mcp.meeting.tencent.com/mcp/wemeet-open/v1 \
  -k TENCENT_MEETING_TOKEN \
  -H 'X-Tencent-Meeting-Token=$TENCENT_MEETING_TOKEN' \
  -H 'X-Skill-Version=v1.0.1' \
  call_command get_meeting -a '{"meeting_id": "xxx"}'
```

#### 取消会议
```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://mcp.meeting.tencent.com/mcp/wemeet-open/v1 \
  -k TENCENT_MEETING_TOKEN \
  -H 'X-Tencent-Meeting-Token=$TENCENT_MEETING_TOKEN' \
  -H 'X-Skill-Version=v1.0.1' \
  call_command cancel_meeting -a '{"meeting_id": "xxx"}'
```

#### 创建周期性会议（JSON 格式参数）
```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://mcp.meeting.tencent.com/mcp/wemeet-open/v1 \
  -k TENCENT_MEETING_TOKEN \
  -H 'X-Tencent-Meeting-Token=$TENCENT_MEETING_TOKEN' \
  -H 'X-Skill-Version=v1.0.1' \
  call_command schedule_meeting -a '{"subject": "每周例会", "start_time": "1773280800", "end_time": "1773284400", "meeting_type": 1, "recurring_rule": {"recurring_type": 2, "until_type": 1, "until_count": 5}}'
```

#### 获取智能纪要
```bash
$PYTHON_CMD -m weclaw.agent.mcp_client \
  -u https://mcp.meeting.tencent.com/mcp/wemeet-open/v1 \
  -k TENCENT_MEETING_TOKEN \
  -H 'X-Tencent-Meeting-Token=$TENCENT_MEETING_TOKEN' \
  -H 'X-Skill-Version=v1.0.1' \
  call_command get_smart_minutes -a '{"record_file_id": "xxx"}'
```

## Notes
- **无需安装任何额外 Python 包，直接使用 `python -m weclaw.agent.mcp_client` 即可**
- **必须通过 `-H` 传入 `X-Tencent-Meeting-Token` 和 `X-Skill-Version` 两个自定义 HTTP 头**
- **`-k TENCENT_MEETING_TOKEN` 传入的是环境变量名，程序会自动从环境变量中读取实际的 token 值**
- **`-H` 参数中的值支持环境变量自动展开**：使用 `$VAR_NAME` 格式，程序会在运行时自动替换为实际的环境变量值（跨平台兼容，Windows PowerShell 和 bash 均可使用）
- 时间参数均为**秒级时间戳**，可通过 `date +%s` 获取当前时间戳
- 周期性会议相关操作需注意传入 `meeting_type=1` 和 `recurring_rule` 对象
- 如果以上工具列表不满足需求，可使用 `list-tools` 命令获取所有可用工具：
  ```bash
  $PYTHON_CMD -m weclaw.agent.mcp_client \
    -u https://mcp.meeting.tencent.com/mcp/wemeet-open/v1 \
    -k TENCENT_MEETING_TOKEN \
    -H 'X-Tencent-Meeting-Token=$TENCENT_MEETING_TOKEN' \
    -H 'X-Skill-Version=v1.0.1' \
    list-tools
  ```
