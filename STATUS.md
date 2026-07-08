# 项目进展与待办

> ShowMo / WinEye ONVIF 相机的 Home Assistant 集成。本仓库 = 单一真相来源(private)。
> 架构与技术约束见 `CLAUDE.md`;本文件是进度 + TODO,方便下次直接接手。

## 已完成

- **ONVIF 鉴权重写**(`custom_components/showmo/pyshowmo/onvif.py`):WS-Security UsernameToken(PasswordDigest)+ WS-Addressing action + SOAP fault 处理;新增服务/媒体 profile 发现、PTZ ops。已真机验证。
- **Motion**:改为"真实订阅成功才暴露传感器",消除永久 unavailable 的死实体(`motion.py:async_initialize`)。
- **PTZ**:`showmo.ptz` 服务(ContinuousMove / Stop / GotoPreset / GotoHomePosition),故障优雅降级(固定镜头返回 not-supported 时只记日志)。
- **单仓库化**:pyshowmo 只保留 vendored 一份;测试迁入 `tests/`,`pytest.ini` 靠 pythonpath 免改任何 import。
- **74 个测试全绿**;CI = hassfest + pytest。
- **HACS 元数据**:`hacs.json`、`manifest.json`(documentation / issue_tracker)、`strings.json`(含 ptz 服务翻译)、`README.md`、`services.yaml`。
- **`CLAUDE.md`** 项目上下文(Claude 启动自动读)。

## 当前状态

- **private** 仓库。内部安装:手动复制 `custom_components/showmo` 到 HA 的 `config/custom_components`,重启。
- **CI 绿**(hassfest + pytest)。HACS 上架校验在 `.github/workflows/validate.yaml` 里注释保留,待转 public 再启用。

## 待办 (TODO)

### 上 HACS(转 public 时一次性做)
- [ ] 仓库转 public
- [ ] 加 topics:`home-assistant homeassistant hacs onvif camera showmo`
- [ ] 加 `LICENSE`(公司定:MIT / Apache-2.0 / 专有)
- [ ] 发 release / tag(如 `v0.1.0`)
- [ ] 提 ShowMo logo PR 到 `home-assistant/brands`
- [ ] CI 里取消注释、重启 `hacs` job(并去掉 `ignore: brands`)

### 功能 / 质量
- [ ] 修复重复的 friendly_name(`puwell WIN2 puwell WIN2`)
- [ ] motion 在"真正实现 ONVIF events"的机型上做端到端验证(当前测试机广告 events 但未实现)
- [ ] `codeowners` 是否填公司 team(现为空)

### 其他
- [ ] 旧 `home_assistant` monorepo 加一行"已迁移至 showmo_HA"指路(可选)

## 下次如何开始

```bash
cd ~/codes/showmo_HA
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
pytest            # 应 74 全绿
```

架构 / 技术约束见 `CLAUDE.md`;真机测试环境等本地信息在开发机本地 memory / `secrets.local.env`(不入库)。
