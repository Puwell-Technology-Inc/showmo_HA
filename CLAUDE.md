# ShowMo Home Assistant 集成 — 项目上下文

> 本文件是这个仓库的单一事实来源。Claude Code 每次启动会自动读取;人也可直接查。
> 交流用中文,代码/命令/标识符保持英文。

## 这是什么

ShowMo / WinEye ONVIF IP 相机的 Home Assistant 自定义集成。功能:直播(RTSP→WebRTC via go2rtc)、快照、ONVIF 自动发现、设备信息、移动侦测(仅当固件真正实现 ONVIF events)、PTZ 服务。

## 仓库定位 —— 唯一真相来源

- **GitHub**: `Puwell-Technology-Inc/showmo_HA`(**私有**)
- **本地**: `~/codes/showmo_HA` —— 以后**只在这里开发**
- 旧的 `~/codes/home_assistant` monorepo(含 pyshowmo external 源、原型、协议工具)**已归档**,不再开发。代码真相全部在本仓库。

## 目录结构(单仓库 = HACS 结构)

```
custom_components/showmo/        集成代码 + vendored pyshowmo(唯一一份)
  pyshowmo/                      厂内 ONVIF/RTSP 客户端库(vendored)
tests/                          集成测试
  pyshowmo/                     pyshowmo 库测试
pytest.ini                      pythonpath 让测试原样跑(见下)
requirements-test.txt           一条命令重建测试环境
hacs.json / README.md
.github/workflows/validate.yaml hassfest + HACS 校验
```

## 开发工作流

```bash
cd ~/codes/showmo_HA
# 首次:
python -m venv .venv && source .venv/bin/activate && pip install -r requirements-test.txt
# 日常:
pytest                 # 74 tests,应全绿
# 改代码 → pytest → git commit → git push
```

`pytest.ini` 的 `pythonpath` 是关键:`.` 解析 `custom_components.showmo.*`;`custom_components/showmo` 让 `import pyshowmo` 命中 vendored 那一份。**所以测试不用改 import,且 pyshowmo 只有 vendored 一份,别再引入 external 副本。**

## 关键技术约束(真机验证过,别踩坑)

- **ONVIF 鉴权分裂**:`GetDeviceInformation`/`GetCapabilities`/`GetServices` 用 HTTP Basic 即可;**Media / PTZ / Events 必须带 WS-Security UsernameToken(PasswordDigest)**,否则返回 `wsse:InvalidSecurity`。事件操作还需 WS-Addressing `action`。构造器在 `pyshowmo/onvif.py`。
- **事件可能是"广告但未实现"**:某些型号广告 `/onvif/events` 却 404。因此 motion `binary_sensor` **只在订阅真正成功时才暴露**(`motion.py:async_initialize` 用一次真实订阅探测),避免出现永远 unavailable 的死实体。
- **PTZ 可能是响应桩**:固定镜头型号 `ContinuousMove` 返回 `ActionNotSupported`、`GotoHome` 返回 `NoProfile`。PTZ 暴露为 `showmo.ptz` **服务**(非实体),故障只记日志、优雅降级。
- **相机 XAddr `to` 要转义**:WS-Addressing 的 `to` 是相机给的订阅 URL,可能含 `&`,构造信封时必须 `xml_escape`。
- SOAP 响应用 `is_soap_fault` 判失败(HTTP 200 也可能是 fault)。

## HACS 发布状态与后续

- **私有仓库进不了 HACS**(HACS 要求 public)。当前定位:公司内部备份/协作。
- **内部安装**:把 `custom_components/showmo` 复制进 HA 的 `config/custom_components`,重启。
- **要上 HACS 时**:转 public + 加 `LICENSE` + 发 release/tag + 提 logo PR 到 `home-assistant/brands`(CI 里暂 `ignore: brands`,合并后去掉)。
- `manifest.json`:owner `Puwell-Technology-Inc`,`codeowners` 目前空(可改公司 team),`documentation`/`issue_tracker` 指向本 repo。

## 提交规范

原子 commit;commit message 结尾加:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
