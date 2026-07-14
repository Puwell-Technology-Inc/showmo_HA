# 项目进展与待办

> ShowMo / WinEye ONVIF 相机的 Home Assistant 集成。本仓库 = 单一真相来源(private)。
> 架构与技术约束见 `CLAUDE.md`;本文件是进度 + TODO,方便下次直接接手。

## 已完成

- **ONVIF 鉴权重写**(`custom_components/showmo/pyshowmo/onvif.py`):WS-Security UsernameToken(PasswordDigest)+ WS-Addressing action + SOAP fault 处理;新增服务/媒体 profile 发现、PTZ ops。已真机验证。
- **Motion**:改为"真实订阅成功才暴露传感器",消除永久 unavailable 的死实体(`motion.py:async_initialize`);轮询任务注册为 entry background task。
- **PTZ**:`showmo.ptz` 服务(ContinuousMove / Stop / GotoPreset / GotoHomePosition),故障优雅降级(固定镜头返回 not-supported 时只记日志)。
- **单仓库化**:pyshowmo 只保留 vendored 一份;测试迁入 `tests/`,`pytest.ini` 靠 pythonpath 免改任何 import;api.py 的 ImportError 双分支 import 已收敛为相对导入单份。
- **Config flow UX**:扫描留空回落出厂默认凭据(admin);密码输入掩码(password selector);错误/abort 文案修正;手动 RTSP 预填 `rtsp://`;修复 friendly_name 重复(主实体不再自带 name)。
- **多 agent 对抗 review 一轮(2026-07-08/09)**:5 维度审查 + 逐条对抗验证,29 报 → 7 驳倒 → 15 个独立问题全部修复,包括:
  - RTSP 凭据 percent-encode/decode 成对修(特殊字符密码不再破坏取流 URL)
  - reconfigure:公共验证提取、serial 保底(探测失败不再覆盖为 None)、wrong_device 校验、unique_id 补写
  - DeviceInfo 统一到 `entity.py::build_device_info`(camera/binary_sensor 不再互相覆盖设备页)
  - 发现安全收敛:XAddrs 绑定 UDP 源 IP(防伪造 ProbeMatch 收割凭据)+ 匿名先行探测(凭据只在 401 后发给同一 host)
  - 死代码清理(~130 行无调用 wrapper、死常量)、discovery 按 IP 去重
- **Reauth(2026-07-14)**:凭据失效自动引导重新认证——加载时探测一次,密码被拒即 `ConfigEntryAuthFailed`(HA 弹重新认证通知,填新密码原地恢复,历史/自动化不断档)。真机发现:此固件 **GetDeviceInformation 匿名可访问**,serial 探测抓不到密码错误;凭据校验改走 media `GetProfiles`(错密返回 HTTP 200 + `wsse:FailedAuthentication` fault,兼容 `ter:NotAuthorized`),并接入 manual/reconfigure/reauth 全部验证路径(此前错密码也能通过验证添加成功——已修复)。真机三分支验证:对/错/离线。
- **106 个测试全绿**;CI = hassfest + pytest。
- **HACS 元数据**:`hacs.json`、`manifest.json`(documentation / issue_tracker)、`strings.json`(含 ptz 服务翻译)、`README.md`、`services.yaml`。
- **`CLAUDE.md`** 项目上下文(Claude 启动自动读)。

## 当前状态

- **private** 仓库。内部安装:手动复制 `custom_components/showmo` 到 HA 的 `config/custom_components`,重启。
- **CI 绿**(hassfest + pytest)。HACS 上架校验在 `.github/workflows/validate.yaml` 里注释保留,待转 public 再启用。
- Config flow 无硬编码连接凭据;出厂默认 admin/123456 仅作扫描步骤留空时的回落(产品决策,厂商确认用户可改密)。

## 待办 (TODO)

### 上 HACS(转 public 时一次性做)
- [x] git 全历史敏感信息扫描(2026-07-14:干净,无 token/私钥,IP 均为私有网段)
- [x] `LICENSE`:**GPL-3.0**(用户拍板 2026-07-14——自研接入,不允许闭源衍生)
- [x] codeowners:`@Puwell-Technology-Inc`
- [ ] 仓库转 public(待公司批准)
- [ ] 加 topics:`home-assistant homeassistant hacs onvif camera showmo`
- [ ] 发 release / tag(如 `v0.1.0`)
- [ ] 提 ShowMo logo PR 到 `home-assistant/brands`(素材已有:`custom_components/showmo/brand/`,icon 256/512 合规;logo 是 icon 副本,只提交 icon 即可)
- [ ] CI 里取消注释、重启 `hacs` job(并去掉 `ignore: brands`)——必须等 public 后,private 会 false-fail
- [ ] (可选)提交 `hacs/default` 进默认商店;在此之前 custom repository 方式 public 后立即可用

### 功能 / 质量
- [ ] motion 在"真正实现 ONVIF events"的机型上做端到端验证(当前测试机广告 events 但未实现)
- [ ] `codeowners` 是否填公司 team(现为空)
- [ ] 与产品负责人确认:RTSP 与 ONVIF 是否同一账号库;默认 RTSP 路径/端口全系一致性;是否强制首次改密
- [ ] (延后)pyshowmo `DiscoveredDevice` 扁平字段与嵌套 device_info 数据重复——纯内部模型重构,review 判 low,churn > 收益,暂不做

### 其他
- [ ] 旧 `home_assistant` monorepo 加一行"已迁移至 showmo_HA"指路(可选)

## 下次如何开始

```bash
cd ~/codes/showmo_HA
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
pytest            # 应 93 全绿
```

架构 / 技术约束见 `CLAUDE.md`;真机测试环境等本地信息在开发机本地 memory / `secrets.local.env`(不入库)。
