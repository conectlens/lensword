//! Resolves the API endpoint the desktop shell is allowed to talk to.
//!
//! This crate carries no Tauri or GUI dependency on purpose. The rule it
//! enforces is a security boundary from ADR 0001 — *"Allow API connections only
//! to the configured local loopback endpoint or an explicit HTTPS origin. Never
//! silently downgrade a remote API to HTTP."* — and a boundary that can only be
//! exercised by building a windowing toolchain is a boundary that stops being
//! exercised.
//!
//! The check lives here rather than in the webview because a check the webview
//! performs is a check the webview can be persuaded to skip.

use std::fmt;

use url::{Host, Url};

/// Why a candidate endpoint was refused.
#[derive(Debug, PartialEq, Eq)]
pub enum ApiConfigError {
    /// Not parseable as an absolute URL.
    Malformed(String),
    /// A scheme other than `http` or `https`.
    UnsupportedScheme(String),
    /// Plain `http` to somewhere other than loopback — the downgrade ADR 0001 forbids.
    InsecureRemote(String),
    /// Parsed, but carries no host to connect to.
    MissingHost,
}

impl fmt::Display for ApiConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Malformed(raw) => {
                write!(f, "not a valid absolute URL: {raw}")
            }
            Self::UnsupportedScheme(scheme) => {
                write!(
                    f,
                    "unsupported scheme `{scheme}`: expected http (loopback only) or https"
                )
            }
            Self::InsecureRemote(host) => write!(
                f,
                "refusing plain http to remote host `{host}`: use https, or a loopback address"
            ),
            Self::MissingHost => write!(f, "URL has no host"),
        }
    }
}

impl std::error::Error for ApiConfigError {}

/// True when the host is the machine itself.
///
/// `Url` resolves `127.0.0.1` and `::1` into [`Host::Ipv4`]/[`Host::Ipv6`], so
/// the whole loopback range is checked numerically rather than by comparing
/// against the one address people usually type. `127.0.0.2` is loopback too.
fn is_loopback(host: &Host<&str>) -> bool {
    match host {
        Host::Domain(name) => name.eq_ignore_ascii_case("localhost"),
        Host::Ipv4(addr) => addr.is_loopback(),
        Host::Ipv6(addr) => addr.is_loopback(),
    }
}

/// Validate a candidate API base URL, returning it in normalized form.
///
/// Accepts any `https` origin, and `http` only when the host is loopback.
pub fn validate_api_base(raw: &str) -> Result<String, ApiConfigError> {
    let trimmed = raw.trim();
    let parsed = Url::parse(trimmed).map_err(|_| ApiConfigError::Malformed(trimmed.to_string()))?;

    let host = parsed.host().ok_or(ApiConfigError::MissingHost)?;

    match parsed.scheme() {
        "https" => {}
        "http" => {
            if !is_loopback(&host) {
                return Err(ApiConfigError::InsecureRemote(host.to_string()));
            }
        }
        other => return Err(ApiConfigError::UnsupportedScheme(other.to_string())),
    }

    // Trailing slashes are stripped so callers can join paths as `{base}{path}`
    // without producing a double slash. `Url` always renders at least "/".
    Ok(trimmed.trim_end_matches('/').to_string())
}

/// Where a resolved endpoint came from. Reported to the frontend so the shell
/// can show which configuration is in force rather than leaving the user to
/// guess why it is talking to the wrong server.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum Source {
    Environment,
    ConfigFile,
    Default,
}

impl Source {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Environment => "environment",
            Self::ConfigFile => "config-file",
            Self::Default => "default",
        }
    }
}

/// A validated endpoint and the configuration layer it came from.
#[derive(Debug, PartialEq, Eq)]
pub struct Resolved {
    pub base_url: String,
    pub source: Source,
}

/// The endpoint used when nothing is configured: a local backend on its
/// documented development port.
pub const DEFAULT_API_BASE: &str = "http://127.0.0.1:8000";

/// Pick an endpoint from the configuration layers, highest precedence first,
/// and validate whichever one wins.
///
/// A layer that is present but blank counts as absent, so an exported-but-empty
/// environment variable does not shadow a real config file.
///
/// A layer that is present and *invalid* is an error, not a reason to fall
/// through to the next one. Falling through would turn a rejected remote
/// endpoint into a silent connection to localhost — the failure would look like
/// a working app pointed at the wrong server, which is precisely the outcome
/// ADR 0001's downgrade rule exists to prevent.
pub fn resolve(env: Option<&str>, config_file: Option<&str>) -> Result<Resolved, ApiConfigError> {
    fn present(v: Option<&str>) -> Option<&str> {
        v.map(str::trim).filter(|v| !v.is_empty())
    }

    let (raw, source) = match (present(env), present(config_file)) {
        (Some(v), _) => (v, Source::Environment),
        (None, Some(v)) => (v, Source::ConfigFile),
        (None, None) => (DEFAULT_API_BASE, Source::Default),
    };

    Ok(Resolved {
        base_url: validate_api_base(raw)?,
        source,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_an_explicit_https_origin() {
        assert_eq!(
            validate_api_base("https://api.example.com").unwrap(),
            "https://api.example.com"
        );
    }

    #[test]
    fn accepts_http_to_ipv4_loopback() {
        assert_eq!(
            validate_api_base("http://127.0.0.1:8000").unwrap(),
            "http://127.0.0.1:8000"
        );
    }

    #[test]
    fn accepts_http_to_localhost() {
        assert_eq!(
            validate_api_base("http://localhost:8000").unwrap(),
            "http://localhost:8000"
        );
    }

    #[test]
    fn accepts_http_to_ipv6_loopback() {
        assert!(validate_api_base("http://[::1]:8000").is_ok());
    }

    #[test]
    fn accepts_any_port_because_a_bundled_backend_binds_a_random_one() {
        // ADR 0001 requires a bundled backend to bind a random loopback port,
        // so the validator must not pin one.
        assert!(validate_api_base("http://127.0.0.1:49731").is_ok());
    }

    #[test]
    fn rejects_plain_http_to_a_remote_host() {
        assert_eq!(
            validate_api_base("http://api.example.com"),
            Err(ApiConfigError::InsecureRemote("api.example.com".into()))
        );
    }

    #[test]
    fn rejects_a_host_that_merely_starts_with_localhost() {
        // `localhost.evil.test` is a remote host whose name has a familiar prefix.
        assert!(matches!(
            validate_api_base("http://localhost.evil.test"),
            Err(ApiConfigError::InsecureRemote(_))
        ));
    }

    #[test]
    fn rejects_a_non_http_scheme() {
        assert!(matches!(
            validate_api_base("file:///etc/passwd"),
            Err(ApiConfigError::UnsupportedScheme(_)) | Err(ApiConfigError::MissingHost)
        ));
    }

    #[test]
    fn rejects_a_relative_or_empty_value() {
        assert!(matches!(
            validate_api_base("/api/v1"),
            Err(ApiConfigError::Malformed(_))
        ));
        assert!(matches!(
            validate_api_base(""),
            Err(ApiConfigError::Malformed(_))
        ));
    }

    #[test]
    fn strips_a_trailing_slash_so_paths_join_cleanly() {
        assert_eq!(
            validate_api_base("https://api.example.com/").unwrap(),
            "https://api.example.com"
        );
    }

    #[test]
    fn environment_outranks_the_config_file() {
        let got = resolve(
            Some("https://env.example.com"),
            Some("https://file.example.com"),
        )
        .unwrap();
        assert_eq!(got.base_url, "https://env.example.com");
        assert_eq!(got.source, Source::Environment);
    }

    #[test]
    fn config_file_is_used_when_the_environment_is_unset() {
        let got = resolve(None, Some("https://file.example.com")).unwrap();
        assert_eq!(got.base_url, "https://file.example.com");
        assert_eq!(got.source, Source::ConfigFile);
    }

    #[test]
    fn falls_back_to_the_loopback_default_when_nothing_is_configured() {
        let got = resolve(None, None).unwrap();
        assert_eq!(got.base_url, DEFAULT_API_BASE);
        assert_eq!(got.source, Source::Default);
    }

    #[test]
    fn a_blank_layer_counts_as_absent() {
        // An exported-but-empty variable must not shadow a real config file.
        let got = resolve(Some("   "), Some("https://file.example.com")).unwrap();
        assert_eq!(got.source, Source::ConfigFile);
    }

    #[test]
    fn an_invalid_layer_is_an_error_rather_than_a_fallthrough() {
        // Falling through would silently point the shell at localhost while the
        // user believes it is talking to the remote server they configured.
        assert_eq!(
            resolve(Some("http://api.example.com"), None),
            Err(ApiConfigError::InsecureRemote("api.example.com".into()))
        );
        assert!(resolve(None, Some("garbage")).is_err());
    }
}
