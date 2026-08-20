// Tauri shell (WP-08).
//
// The window is thin on purpose: it starts the bundled backend on a loopback
// port, waits for readiness, and points the webview at the static frontend.
// Research logic lives in the Python service, so the desktop build and the
// server deployment cannot drift apart.

use std::process::{Child, Command};
use std::time::{Duration, Instant};

const BACKEND_PORT: u16 = 8765;

fn spawn_backend() -> std::io::Result<Child> {
    Command::new("qra-server")
        .args(["--host", "127.0.0.1", "--port", &BACKEND_PORT.to_string()])
        // Offline by default: the desktop build reads the bundled replica and
        // only reaches the network when the researcher configures a provider.
        .env("QRA_DATABASE_URL", "sqlite:///replica/qra.sqlite")
        .env("QRA_OFFLINE", "1")
        .spawn()
}

fn wait_for_ready(timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if reqwest::blocking::get(format!("http://127.0.0.1:{BACKEND_PORT}/meta/ready"))
            .map(|r| r.status().is_success())
            .unwrap_or(false)
        {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

fn main() {
    let mut backend = spawn_backend().expect("failed to start the bundled backend");

    if !wait_for_ready(Duration::from_secs(30)) {
        // Fail loudly. A window showing an empty corpus looks like a working
        // app that has lost the Qur'an, which is the worst possible failure.
        eprintln!("backend did not become ready; refusing to open a window over an empty corpus");
        let _ = backend.kill();
        std::process::exit(1);
    }

    tauri::Builder::default()
        .setup(|_app| Ok(()))
        .run(tauri::generate_context!())
        .expect("error while running tauri application");

    let _ = backend.kill();
}
