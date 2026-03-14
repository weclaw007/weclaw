---
name: amap
description: 高德地图地理信息服务，支持地理编码、逆地理编码、IP定位、天气查询、路线规划（骑行、步行、驾车、公交）、距离测量、关键词搜索、周边搜索、地点详情等功能。使用 mcp_client.py 脚本调用。
homepage: https://dashscope.aliyuncs.com/api/v1/mcps/amap-maps/sse
metadata:
  {
    "openclaw":
      {
        "emoji": "🗺️",
        "primaryEnv": "DASHSCOPE_API_KEY",
        "requires": { "bins": ["python"] }
      },
  }
---

# AMap 高德地图

基于高德地图的地理信息服务，提供位置相关功能。通过 `mcp_client.py` 脚本调用远程服务。

## Available Tools

### 1. `maps_geo` - 地理编码
将详细的结构化地址转换为经纬度坐标。支持对地标性名胜景区、建筑物名称解析为经纬度坐标。
- **address** (string, 必填): 待解析的结构化地址信息
- **city** (string, 可选): 指定查询的城市

### 2. `maps_regeocode` - 逆地理编码
将一个高德经纬度坐标转换为行政区划地址信息。
- **location** (string, 必填): 经纬度

### 3. `maps_ip_location` - IP定位
根据用户输入的 IP 地址，定位 IP 的所在位置。
- **ip** (string, 必填): IP地址

### 4. `maps_weather` - 天气查询
根据城市名称或者标准adcode查询指定城市的天气。
- **city** (string, 必填): 城市名称或者adcode

### 5. `maps_direction_bicycling` - 骑行路径规划
规划骑行通勤方案，考虑天桥、单行线、封路等情况。最大支持 500km 的骑行路线规划。
- **origin** (string, 必填): 出发点经纬度，坐标格式为：经度，纬度
- **destination** (string, 必填): 目的地经纬度，坐标格式为：经度，纬度

### 6. `maps_direction_walking` - 步行路径规划
规划100km 以内的步行通勤方案。
- **origin** (string, 必填): 出发点经度，纬度，坐标格式为：经度，纬度
- **destination** (string, 必填): 目的地经度，纬度，坐标格式为：经度，纬度

### 7. `maps_direction_driving` - 驾车路径规划
根据用户起终点经纬度坐标规划以小客车、轿车通勤出行的方案。
- **origin** (string, 必填): 出发点经纬度，坐标格式为：经度，纬度
- **destination** (string, 必填): 目的地经纬度，坐标格式为：经度，纬度

### 8. `maps_direction_transit_integrated` - 公共交通路径规划
综合各类公共（火车、公交、地铁）交通方式的通勤方案，跨城场景下必须传起点城市与终点城市。
- **origin** (string, 必填): 出发点经纬度，坐标格式为：经度，纬度
- **destination** (string, 必填): 目的地经纬度，坐标格式为：经度，纬度
- **city** (string, 必填): 公共交通规划起点城市
- **cityd** (string, 必填): 公共交通规划终点城市

### 9. `maps_distance` - 距离测量
测量两个经纬度坐标之间的距离，支持驾车、步行以及球面距离测量。
- **origins** (string, 必填): 起点经度，纬度，可以传多个坐标，使用竖线隔离，比如120,30|120,31
- **destination** (string, 必填): 终点经度，纬度，坐标格式为：经度，纬度
- **type** (string, 可选): 距离测量类型，1代表驾车距离测量，0代表直线距离测量，3步行距离测量

### 10. `maps_text_search` - 关键词搜索
根据用户输入的关键字进行 POI 搜索，并返回相关的信息。
- **keywords** (string, 必填): 查询关键字
- **city** (string, 可选): 查询城市
- **citylimit** (boolean, 可选): 是否限制城市范围内搜索，默认不限制

### 11. `maps_around_search` - 周边搜索
根据用户传入关键词以及坐标location，搜索出radius半径范围的POI。
- **keywords** (string, 必填): 搜索关键词
- **location** (string, 必填): 中心点经度纬度
- **radius** (string, 可选): 搜索半径

### 12. `maps_search_detail` - 地点详情查询
查询关键词搜或者周边搜获取到的POI ID的详细信息。
- **id** (string, 必填): 关键词搜或者周边搜获取到的POI ID

### 13. `maps_schema_navi` - 唤起导航
返回一个拼装好的客户端唤醒URI，用户点击即可唤起高德地图APP跳转到导航页面。
- **lon** (string, 必填): 终点经度
- **lat** (string, 必填): 终点纬度

### 14. `maps_schema_take_taxi` - 唤起打车
返回一个拼装好的客户端唤醒URI，直接唤起高德地图进行打车。直接展示生成的链接，不需要总结。
- **slon** (string, 可选): 起点经度
- **slat** (string, 可选): 起点纬度
- **sname** (string, 可选): 起点名称
- **dlon** (string, 必填): 终点经度
- **dlat** (string, 必填): 终点纬度
- **dname** (string, 必填): 终点名称

### 15. `maps_schema_personal_map` - 行程规划地图展示
将行程规划位置点按照行程顺序在高德地图展示，返回结果为高德地图打开的URI链接，该结果不需总结，直接返回。
- **orgName** (string, 必填): 行程规划地图小程序名称
- **lineList** (array, 必填): 行程列表，每项包含：
  - **title** (string, 必填): 行程名称描述（按行程顺序）
  - **pointInfoList** (array, 必填): 行程目标位置点描述，每项包含：
    - **name** (string, 必填): 行程目标位置点名称
    - **lon** (number, 必填): 行程目标位置点经度
    - **lat** (number, 必填): 行程目标位置点纬度
    - **poiId** (string, 必填): 行程目标位置点POIID

## Quick Start

Python command compatibility (some machines use `python`, others use `python3`):

```bash
PYTHON_CMD=$(command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
```

Load API key from environment variable:

```python
import os
api_key = os.getenv("DASHSCOPE_API_KEY")
```

调用工具示例（以天气查询为例）：

```bash
$PYTHON_CMD mcp_client.py \
  -u https://dashscope.aliyuncs.com/api/v1/mcps/amap-maps/sse \
  -k $DASHSCOPE_API_KEY \
  call-tool maps_weather -a '{"city": "北京"}'
```

## Notes

- 需要 DashScope API Key（环境变量 `DASHSCOPE_API_KEY`）
- 坐标格式：`经度,纬度`（如 `116.397428,39.90923`）
- 城市名称支持中文
- 距离单位为米，坐标系使用 GCJ-02（国测局坐标系）
- 注意 DashScope 配额限制
- **无需安装任何额外 Python 包，直接使用 mcp_client.py 即可**
- 如果以上工具列表不满足需求，可使用 `list-tools` 命令获取所有可用工具：
  ```bash
  $PYTHON_CMD mcp_client.py \
    -u https://dashscope.aliyuncs.com/api/v1/mcps/amap-maps/sse \
    -k $DASHSCOPE_API_KEY \
    list-tools
  ```
