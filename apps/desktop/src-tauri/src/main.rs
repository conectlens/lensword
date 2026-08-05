// Keeps a console window from appearing alongside the app on Windows release
// builds. Debug builds keep it, since that is where stdout is worth reading.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    lensword_desktop_lib::run()
}
