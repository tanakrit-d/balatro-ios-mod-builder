"""Build static iOS OpenSSL and adapt MPAPI's desktop loader for the app."""

import hashlib
import io
import json
import os
import subprocess
import tarfile
import urllib.request

VERSION = "3.5.9"
SOURCE_SHA256 = "603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a"
SOURCE_URL = f"https://github.com/openssl/openssl/releases/download/openssl-{VERSION}/openssl-{VERSION}.tar.gz"


def lock_entry():
    return {"version": VERSION, "source_sha256": SOURCE_SHA256, "adapter": 1}


def validate_runtime(files, app):
    try:
        metadata = json.loads(files[app + "builder-openssl.json"])
        ca = files[app + "tls/cacert.pem"]
    except (KeyError, ValueError) as error:
        raise ValueError(
            "PvP requires iOS OpenSSL; rebuild with scripts/runtime.py"
        ) from error
    if (
        metadata.get("version") != VERSION
        or metadata.get("source_sha256") != SOURCE_SHA256
        or metadata.get("platform") != "ios-arm64"
        or metadata.get("linkage") != "static"
        or metadata.get("ca_sha256") != hashlib.sha256(ca).hexdigest()
    ):
        raise ValueError(
            "Incompatible iOS OpenSSL runtime; rebuild with scripts/runtime.py"
        )


def verify_exports(executable):
    exports = subprocess.check_output(
        ["xcrun", "dyld_info", "-exports", str(executable)], text=True
    )
    symbols = {line.split()[-1] for line in exports.splitlines() if line.split()}
    required = {
        "_OPENSSL_init_ssl",
        "_TLS_client_method",
        "_SSL_CTX_new",
        "_SSL_connect",
        "_SSL_read",
        "_SSL_write",
        "_RAND_bytes",
        "_EVP_sha256",
        "_HMAC",
        "_EVP_aes_256_gcm",
    }
    missing = required - symbols
    if missing:
        raise ValueError(
            "iOS OpenSSL symbols are not exported: " + ", ".join(sorted(missing))
        )


def build(work):
    work.mkdir(parents=True, exist_ok=True)
    archive = work / "openssl.tar.gz"
    if not archive.exists():
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
            archive.write_bytes(response.read())
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("OpenSSL source checksum mismatch")
    source = work / f"openssl-{VERSION}"
    if not source.exists():
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(work, filter="data")
    env = os.environ.copy()
    env["SDKROOT"] = subprocess.check_output(
        ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True
    ).strip()
    subprocess.run(
        [
            "perl",
            "Configure",
            "ios64-xcrun",
            "no-shared",
            "no-tests",
            "no-module",
            "no-apps",
            "no-docs",
            "-miphoneos-version-min=15.0",
            f"--prefix={work / 'install'}",
        ],
        cwd=source,
        env=env,
        check=True,
    )
    subprocess.run(["make", "-j6"], cwd=source, env=env, check=True)
    ca = work / "cacert.pem"
    if not ca.exists():
        with urllib.request.urlopen(
            "https://curl.se/ca/cacert.pem", timeout=120
        ) as response:
            ca.write_bytes(response.read())
    if b"-----BEGIN CERTIFICATE-----" not in ca.read_bytes():
        raise ValueError("Invalid CA bundle")
    return source


def linker_flags(source):
    # LuaJIT resolves ffi.C dynamically. Retain and export even symbols which
    # have no native call sites; ordinary static linking/dead stripping loses them.
    return (
        f" -Wl,-force_load,{source / 'libssl.a'}"
        f" -Wl,-force_load,{source / 'libcrypto.a'}"
        " -Wl,-export_dynamic"
    )


def resources(work):
    return {
        "tls/cacert.pem": (work / "cacert.pem").read_bytes(),
        "tls/LICENSE-OpenSSL.txt": (
            work / f"openssl-{VERSION}" / "LICENSE.txt"
        ).read_bytes(),
        "builder-openssl.json": json.dumps(
            {
                "version": VERSION,
                "source_sha256": SOURCE_SHA256,
                "platform": "ios-arm64",
                "linkage": "static",
                "ca_sha256": hashlib.sha256(
                    (work / "cacert.pem").read_bytes()
                ).hexdigest(),
            },
            sort_keys=True,
        ).encode(),
    }


def patch_mods(mods):
    path = "MultiplayerAPI/networking/openssl_ffi.lua"
    text = mods[path].decode()
    anchor = "local function load_openssl()\n\tif openssl_loaded then\n\t\treturn true\n\tend\n"
    if text.count(anchor) != 1:
        raise ValueError("MPAPI OpenSSL loader changed; inspect iOS adapter")
    adapter = """
	-- The iOS runtime links OpenSSL statically and exports it for every Lua
	-- state, including networking workers. Never dlopen the desktop dylibs.
	if os.getenv('BMP_IOS_OPENSSL') == '1' then
		local ok, err = pcall(function()
			ssl_lib, crypto_lib = ffi.C, ffi.C
			if ssl_lib.OPENSSL_init_ssl(OPENSSL_INIT_LOAD_SSL_STRINGS + OPENSSL_INIT_LOAD_CRYPTO_STRINGS, nil) ~= 1 then
				error('iOS OpenSSL initialization failed')
			end
			-- Resolve the key entry points before advertising TLS availability.
			assert(ssl_lib.TLS_client_method() ~= nil)
			assert(crypto_lib.EVP_sha256() ~= nil)
		end)
		if not ok then
			ssl_error('iOS static OpenSSL: ' .. tostring(err))
			return false, err
		end
		openssl_loaded = true
		ssl_log('Using OpenSSL linked into the iOS runtime')
		return true
	end
"""
    mods[path] = text.replace(anchor, anchor + adapter).encode()
    for name in list(mods):
        if name.startswith("MultiplayerAPI/networking/") and name.endswith(
            (".dylib", ".dll")
        ):
            del mods[name]
