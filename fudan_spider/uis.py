"""
UIS 统一身份认证模块
新系统: id.fudan.edu.cn (BambooCloud IDP, Vue SPA + JSON API)

登录流程:
  1. GET  /authserver/login?service=...  → 跟踪重定向，拿 lck token
  2. POST /idp/authn/queryAuthMethods    → 拿 authChainCode / requestType
  3. POST /idp/authn/getJsPublicKey      → 拿 RSA 公钥
  4. POST /idp/authn/authExecute         → 提交加密密码（第一步）
     → 若 pageLevelNo=2，需要 MFA 第二步（TOTP / 短信）
  5. POST /idp/authn/authExecute         → 提交 OTP（第二步，可选）
  6. POST /idp/authCenter/authnEngine    → 用 loginToken 完成 CAS，拿 service Cookie

MFA 配置:
  - TOTP（推荐）: 在 .env 中设置 fudan_otp_secret=<base32密钥>，可全自动登录
  - 如未配置 TOTP，触发 MFA 时抛出 RuntimeError，需用户手动处理
"""

import os
import re
import base64
import html

import pyotp
import requests
from requests import Session
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

BASE = "https://id.fudan.edu.cn"
IDP  = f"{BASE}/idp"
UA   = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def build_session() -> Session:
    se = Session()
    se.headers.update({"User-Agent": UA})
    return se


def _rsa_encrypt(plaintext: str, public_key_b64: str) -> str:
    """用服务器返回的 Base64 公钥（PKCS#8 DER）对明文做 RSA/PKCS1v15 加密"""
    der = base64.b64decode(public_key_b64)
    key = RSA.import_key(der)
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(plaintext.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def login(
    username: str = None,
    password: str = None,
    otp_secret: str = None,
    service: str = "https://my.fudan.edu.cn/",
) -> Session:
    """
    完成 UIS 登录（含 MFA），返回已认证的 Session。

    :param username:   学号，默认读取环境变量 fudan_username
    :param password:   密码，默认读取环境变量 fudan_password
    :param otp_secret: TOTP 密钥（base32），默认读取 fudan_otp_secret
                       配置后可全自动完成 MFA；未配置时触发 MFA 抛 RuntimeError
    :param service:    目标服务，默认 my.fudan.edu.cn
    :raises ValueError:   未提供账号密码
    :raises RuntimeError: 触发验证码 / 登录失败 / 未配置 TOTP 的 MFA
    """
    username   = username   or os.getenv("fudan_username")
    password   = password   or os.getenv("fudan_password")
    otp_secret = otp_secret or os.getenv("fudan_otp_secret", "")
    if not username or not password:
        raise ValueError(
            "未提供账号或密码，请设置环境变量 fudan_username / fudan_password"
        )

    se      = build_session()
    referer = f"{BASE}/ac/"

    # ── Step 1: 获取 lck ──────────────────────────────────────
    r = se.get(
        f"{BASE}/authserver/login",
        params={"service": service},
        allow_redirects=True,
    )
    match = re.search(r"lck=([\w_-]+)", r.url)
    if not match:
        raise RuntimeError(f"无法从重定向 URL 中提取 lck token，当前 URL: {r.url}")
    lck     = match.group(1)
    referer = r.url

    # ── Step 2: queryAuthMethods ──────────────────────────────
    r2 = se.post(
        f"{IDP}/authn/queryAuthMethods",
        json={"lck": lck},
        headers={"Referer": referer},
    )
    r2.raise_for_status()
    body2 = r2.json()
    if str(body2.get("code")) not in ("200", "4339"):
        raise RuntimeError(f"queryAuthMethods 失败: {body2.get('message')}")

    entity_id    = body2.get("entityId") or service.rstrip("/")
    request_type = body2.get("requestType", "chain_type")

    # 找 userAndPwd 所在的认证链
    modules = body2.get("data") or []
    chain = next(
        (m for m in modules if "userAndPwd" in (m.get("moduleCodes") or [])),
        modules[0] if modules else {}
    )
    auth_chain_code = chain.get("authChainCode", "")

    # ── Step 3: 获取 RSA 公钥 ─────────────────────────────────
    r3 = se.post(f"{IDP}/authn/getJsPublicKey", headers={"Referer": referer})
    r3.raise_for_status()
    body3 = r3.json()
    if str(body3.get("code")) != "200":
        raise RuntimeError(f"获取公钥失败: {body3.get('message')}")
    pub_b64 = (
        body3["data"]["data"] if isinstance(body3.get("data"), dict)
        else body3["data"]
    )

    # ── Step 4: 密码认证（authExecute 第一步） ────────────────
    encrypted_password = _rsa_encrypt(password, pub_b64)

    r4 = se.post(
        f"{IDP}/authn/authExecute",
        json={
            "authModuleCode": "userAndPwd",
            "authChainCode":  auth_chain_code,
            "entityId":       entity_id,
            "requestType":    request_type,
            "lck":            lck,
            "authPara": {
                "loginName":  username,
                "password":   encrypted_password,
                "verifyCode": "",
            },
        },
        headers={"Referer": referer},
    )
    r4.raise_for_status()
    body4 = r4.json()

    if str(body4.get("code")) not in ("200",):
        raise RuntimeError(
            f"authExecute(密码) 失败 (code={body4.get('code')}): {body4.get('message')}"
        )

    login_token  = body4.get("loginToken")
    page_level   = body4.get("pageLevelNo", 0)
    chain_code2  = body4.get("authChainCode", auth_chain_code)
    req_number   = body4.get("requestNumber")
    mfa_modules  = body4.get("moduleCodes", [])

    # ── Step 5: MFA 第二步（TOTP） ────────────────────────────
    if not login_token and page_level == 2:
        if not otp_secret:
            raise RuntimeError(
                "账号已开启 MFA 增强认证，请在 .env 中配置 fudan_otp_secret（TOTP 密钥）\n"
                f"可用的 MFA 方式: {mfa_modules}"
            )
        if "userAndOtp" not in mfa_modules:
            raise RuntimeError(
                f"账号 MFA 不支持 TOTP，可用方式: {mfa_modules}\n"
                "请在 id.fudan.edu.cn 个人中心开启 TOTP（动态口令）认证"
            )

        totp = pyotp.TOTP(otp_secret)
        otp_code = totp.now()

        r5 = se.post(
            f"{IDP}/authn/authExecute",
            json={
                "authModuleCode": "userAndOtp",
                "authChainCode":  chain_code2,
                "entityId":       entity_id,
                "requestType":    request_type,
                "lck":            lck,
                "requestNumber":  req_number,
                "authPara": {
                    "loginName":  username,
                    "otpCode":    otp_code,
                    "verifyCode": "",
                },
            },
            headers={"Referer": referer},
        )
        r5.raise_for_status()
        body5 = r5.json()

        if str(body5.get("code")) not in ("200",):
            raise RuntimeError(
                f"authExecute(OTP) 失败 (code={body5.get('code')}): {body5.get('message')}"
            )
        login_token = body5.get("loginToken")

    if not login_token:
        raise RuntimeError(f"登录失败，未获取到 loginToken，最终响应: {body4}")

    # ── Step 6: 用 loginToken 完成 CAS ───────────────────────
    r6 = se.post(
        f"{IDP}/authCenter/authnEngine",
        data={"loginToken": login_token},
        headers={"Referer": referer},
        allow_redirects=False,
    )
    r6.raise_for_status()

    # authnEngine 返回一段 HTML，其中 doSubmit() 用 JS 跳转到带 ticket 的 URL
    # 格式: var locationValue = "https://my.fudan.edu.cn/?ticket=ST-xxx";
    ticket_match = re.search(
        r'var\s+locationValue\s*=\s*"([^"]+)"', r6.text
    )
    if not ticket_match:
        raise RuntimeError(
            f"authnEngine 响应中未找到 locationValue，响应: {r6.text[:300]}"
        )

    ticket_url = html.unescape(ticket_match.group(1))
    r7 = se.get(ticket_url, allow_redirects=True)
    r7.raise_for_status()

    return se
