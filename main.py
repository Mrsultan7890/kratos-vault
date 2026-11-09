import sys
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from core.database import DB_PATH, Database
from core.enrichment import configure_status_encryption, reset_stuck_statuses
from ui.main_window import MainWindow, VaultPasswordDialog


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Kratos Vault")
    app.setApplicationVersion("2.1")

    plaintext_vault = False
    if DB_PATH.exists():
        with DB_PATH.open("rb") as vault_file:
            plaintext_vault = vault_file.read(16) == b"SQLite format 3\x00"

    while True:
        dialog = VaultPasswordDialog(
            existing=DB_PATH.exists() and not plaintext_vault,
            plaintext_migration=plaintext_vault)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return 0
        try:
            db = Database(password=dialog.password())
            break
        except Exception as exc:
            QMessageBox.critical(
                None, "Vault Could Not Be Opened",
                f"The vault was not opened or changed:\n{exc}\n\n"
                "Check the password, or verify the vault file before trying again.")

    try:
        configure_status_encryption(dialog.password())
        reset_stuck_statuses()
    except Exception as exc:
        db.close()
        QMessageBox.critical(
            None, "Enrichment Status Could Not Be Unlocked",
            f"The vault opened, but its status file could not be read safely:\n{exc}")
        return 1
    window = MainWindow(db)
    window.show()

    exit_code = app.exec()
    window.shutdown_workers()
    db.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
