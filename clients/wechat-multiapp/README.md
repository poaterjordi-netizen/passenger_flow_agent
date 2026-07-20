# 客流智控多端应用

本目录是与原微信小程序隔离的微信多端应用工程。源代码位于
`miniprogram/`，面向 Android、iOS 和 HarmonyOS；原小程序仍保留在
`../wechat-miniprogram/`，两者互不覆盖。

## 固定标识

- 应用名称：`客流智控`
- 版本：`0.1.0`（版本号 `1`）
- 微信小程序 AppID：`wxcec9562590faa1a0`
- Android applicationId：`com.sunxb.metroflow`
- iOS Bundle ID：`com.sunxb.metroflow`
- HarmonyOS bundleName：`com.sunxb.metroflow`

上述标识的可审计基线保存在 `multiapp.manifest.json`。各平台最终构建时，
还必须在微信多端应用后台和签名配置中使用相同包名。

`project.miniapp.json` 也分别固定了 `mini-android.packageName`、
`mini-ios.bundleId` 和 `mini-ohos.bundleName`。微信云构建仍会以后台绑定的
移动应用信息为准；后台标识没有配置完成时，本地字段不会把默认调试包名
变成可发布包名。

## 数据与安全边界

默认运行 `embedded-synthetic-read-only` 模式，完全使用仓库内合成数据，
不需要域名，也不会连接数据库。可选 HTTPS 模式只接受配置好的受控 API；
客户端不生成或执行自由 SQL。

禁止提交 AppSecret、SDK Key/Secret、数据库凭据、访问令牌、签名文件、
描述文件和 `project.private.config.json`。

## 微信开发者工具

1. 导入本目录并使用 AppID `wxcec9562590faa1a0`。
2. 切换至“多端应用模式”，确认已绑定对应的多端应用。
3. 点击“编译”，在模拟器核验总览、查询、预测和设置页面。
4. 使用标题栏的构建入口生成 Android APK、iOS IPA 或 HarmonyOS APP。

本地快速校验：

```bash
python3 scripts/check_multiapp.py
node --test clients/wechat-multiapp/tests/synthetic-api.test.js
find clients/wechat-multiapp/miniprogram -name '*.js' -print0 \
  | xargs -0 -n1 node --check
```

## 三个平台的构建前提

- Android：测试包可使用调试签名；对外发布必须换成长期保存的正式签名。
- iOS：IPA 必须使用 Apple Developer 证书和匹配的 provisioning profile；
  本机还需要完整 Xcode，或选择微信提供的远程构建。
- HarmonyOS：需要微信后台开通 HarmonyOS 构建能力；发布包还需要华为
  AppGallery Connect 的证书、Profile 与正式签名。

在生成可安装包前，先在微信多端应用的移动应用信息中确认以下三个值已由
后台下发，且与本工程一致：

- Android `android_package_name`：`com.sunxb.metroflow`
- iOS `bundle_id`：`com.sunxb.metroflow`
- HarmonyOS `ohos_bundle_id`：`com.sunxb.metroflow`

微信默认的 Android `com.tencent.weauth` 和 iOS
`com.tencent.devtoolssaaademo.db` 只用于临时调试，不是本项目交付标识。
如果构建产物仍使用这两个值，不得把它作为体验版或正式安装包分发。

Android 调试签名可以用于本机安装测试；iOS 必须提供后缀为
`.mobileprovision` 的描述文件及匹配证书；HarmonyOS 必须提供匹配包名的
Profile、应用证书和签名密钥。所有签名材料只保存在本机，不进入 Git。

生成的 `build/`、`miniapp/`、APK/AAB、IPA、HAP/APP 和签名文件均已从
Git 排除。

## 2026-07-20 构建状态

当前能够安全完成的内容已经完成：

- 微信后台已下发三个正式标识，均为 `com.sunxb.metroflow`。
- 模拟器正常显示总览、查询、预测和设置页，数据模式为
  `embedded-synthetic-read-only`。
- Android 调试包位于
  `build/android/metroflow-0.1.0-debug.apk`，包名已从二进制 Manifest 复核，
  ZIP 完整性和 APK Signature Scheme v2/v3 均验证通过。
- 当前 Android 调试包 SHA-256 为
  `e6952bb3a58c94c20fc7d0b43d69544306d744be32c7c9cb0946965ed9b38931`。
- 该 APK 使用微信开发者工具自带的 Android Debug 证书，只能用于本机安装
  和功能验证，不得作为商店正式发布包。
- iOS 与 HarmonyOS 的源码、包名和本机 CSR 已准备好，但外部账号签发与
  最终安装包按用户要求暂缓。
- 微信开发者工具临时服务端口 `18489` 已关闭。

Android 构建工具在 Apple Silicon 上可能生成 APK 后因内置 Intel
`zipalign` 被 macOS 强制终止。遇到这种情况只能对已生成的调试 APK 使用同一
微信工具包中的 `apksigner.jar` 完成调试签名并再次验证；不得修改供应商二进制、
绕过 Gatekeeper，或把该方法当作正式发布签名流程。

## 本机签名材料位置

签名材料全部保存在仓库外：

```text
~/Library/Application Support/PassengerFlowAgent/signing/
├── ios/
│   ├── metroflow-ios-private-key.pem
│   └── metroflow-ios.csr
└── harmonyos/
    ├── metroflow-harmonyos.p12
    └── metroflow-harmonyos.csr
```

目录权限为 `700`，私钥、CSR 和密钥库权限为 `600`。随机密码保存在 macOS
钥匙串的以下服务中，不写入文档、命令历史或 Git：

- `PassengerFlowAgent iOS Private Key Password`
- `PassengerFlowAgent iOS P12 Export Password`
- `PassengerFlowAgent HarmonyOS Store Password`
- `PassengerFlowAgent HarmonyOS Key Password`

不要移动这些文件到仓库。CSR 可以提交给对应的官方开发者平台；私钥不能上传。
微信远程云构建如果要求上传 `.p12` 和密码，会把敏感签名材料发送给腾讯构建服务，
恢复构建时必须再次获得明确授权。

## 以后恢复 iOS

当前 Apple 账户已经能够登录，但尚未加入 Apple Developer Program。恢复时：

1. 由账户持有人在 iPhone、iPad 或 Mac 的 Apple Developer App 中完成入会、
   身份验证、协议确认和付款，并确认会员状态为 Active。
2. 在 Apple Developer 中用 `metroflow-ios.csr` 申请匹配证书。
3. 创建或确认 App ID `com.sunxb.metroflow`。
4. 创建并下载匹配的 `.mobileprovision`。
5. 使用本机加密私钥和 Apple 返回的证书导出 `.p12`；密码继续存入钥匙串。
6. 通过微信开发者工具远程构建 IPA，并核验 IPA 内的 Bundle ID、版本和签名。

没有 Active 会员、匹配证书和 provisioning profile 时，不应反复尝试 IPA 构建。

## 以后恢复 HarmonyOS

当前没有完成华为开发者账号认证，按用户要求暂缓。恢复时：

1. 登录并完成华为开发者/AppGallery Connect 所需的账户认证。
2. 创建或确认 Bundle ID `com.sunxb.metroflow`。
3. 上传 `metroflow-harmonyos.csr`，下载匹配的应用证书 `.cer` 和 Profile `.p7b`。
4. 在微信开发者工具中选择仓库外的 `.p12`、`.cer` 和 `.p7b`，密码从 macOS
   钥匙串读取，Key alias 为 `metroflow`。
5. 先构建开发版并在真实 HarmonyOS 设备上验收；正式上架必须另走正式签名、
   合规和审核流程。

任何付费、协议、权限扩大、证书上传、体验分发或正式发布，都需要在实际执行前
再次确认。
