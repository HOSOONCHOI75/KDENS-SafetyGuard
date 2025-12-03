# =====================================
# KDENS SafetyGuard — MAIN WINDOW powered by 최호순
# =====================================

import sys
import os
from pathlib import Path           # ✅ 로그 경로용
from datetime import datetime      # ✅ 로그 타임스탬프용
import traceback                   # ✅ 예외 스택 기록용

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QMessageBox,      # ✅ 약관/오류 다이얼로그
    QInputDialog,     # ✅ (예비) 입력 다이얼로그
    QDialog,
)
from PySide6.QtGui import QIcon

# -------------------------
# Python Path 설정
# -------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

# -------------------------
# 리소스 경로 헬퍼 (PyInstaller exe / 개발환경 모두 지원)
# -------------------------
def resource_path(relative_path: str) -> str:
    """
    assets 같은 리소스 파일의 실제 경로를 반환합니다.
    - 개발환경: main.py가 있는 폴더를 기준으로
    - PyInstaller exe: _MEIPASS(원파일) 또는 exe가 있는 폴더를 기준으로
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 환경
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # 일반 파이썬 실행
        base_path = BASE_DIR
    return os.path.join(base_path, relative_path)


# 🔹 업데이트 알림 모듈 임포트
from updater import check_for_update

# 🔹 라이선스 / 텔레메트리 모듈
from license_manager import load_license, save_license, generate_serial, LicenseInfo
from telemetry import send_event

# -------------------------
# UI IMPORTS
# -------------------------
from ui.sidebar import Sidebar
from ui.splash_screen import KdensSplashScreen
from ui.dashboard_view import DashboardView
from ui.hazard9_view import Hazard9View
from ui.pipeguard_view import PipeGuardView
from ui.final_risk_view import FinalRiskView
from ui.report_input_view import ReportInputView
from ui.report_history import ReportHistoryView   # ✅ 파일 이름에 맞게 수정
from ui.windguard_view import WindGuardView       # ✅ WindGuard 2.0 화면 추가
from ui.terms_dialog import TermsDialog           # ✅ 약관/정보수집 다이얼로그

# -------------------------
# ENGINE IMPORTS
# -------------------------
from risk_engine.hazard9_engine import Hazard9Engine
from pipeguard.engine import PipeGuardEngine


# ================================
# 라이선스 / 약관 동의 처리 함수
# ================================
def _get_field(info, name, default=None):
    """dict / dataclass 모두 지원용 헬퍼."""
    if info is None:
        return default
    if isinstance(info, dict):
        return info.get(name, default)
    return getattr(info, name, default)


def ensure_license(parent=None):
    """
    1) 기존 라이선스 + 약관 동의 완료 → startup 이벤트만 전송 후 바로 반환
    2) 없거나 약관 미동의 → TermsDialog로 조직명/사용자/약관 동의 + install 이벤트 전송
    3) 약관 거부/취소 → None 반환 (호출 측에서 앱 종료)
    """
    try:
        info = load_license()
    except Exception:
        info = None

    # ===== 이미 동의한 경우: startup 이벤트만 전송 =====
    if info and _get_field(info, "accepted_terms", False):
        serial = _get_field(info, "serial", "")
        org_name = _get_field(info, "org_name", "")
        user_name = _get_field(info, "user_name", "")
        if serial and org_name and user_name:
            try:
                send_event(serial, org_name, user_name, "startup")
            except Exception:
                # 네트워크 오류 등은 무시
                pass
        return info

    # ===== 첫 실행 또는 약관 미동의: TermsDialog로 처리 =====
    existing_org = _get_field(info, "org_name", "")
    existing_user = _get_field(info, "user_name", "")
    existing_serial = _get_field(info, "serial", "")

    dialog = TermsDialog(parent=parent)
    if existing_org:
        dialog.org_edit.setText(existing_org)
    if existing_user:
        dialog.user_edit.setText(existing_user)

    result = dialog.exec()
    # QDialog 클래스 상수와 비교해야 함 (dialog.Accepted ❌)
    if result != QDialog.Accepted:
        # 약관에 동의하지 않으면 프로그램 종료
        return None

    org_name = dialog.org_name
    user_name = dialog.user_name

    # 기존 시리얼이 있으면 그대로 사용, 없으면 새로 생성
    serial = existing_serial or generate_serial(org_name)

    info = LicenseInfo(
        org_name=org_name,
        user_name=user_name,
        serial=serial,
        accepted_terms=True,
    )

    try:
        save_license(info)
    except Exception:
        # 저장 오류가 나도 일단 계속 사용 가능하도록
        pass

    # install 이벤트 기록
    try:
        send_event(serial, org_name, user_name, "install")
    except Exception:
        pass

    return info


# ================================
# Main Window
# ================================
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        # Window 설정
        self.setWindowTitle("KDENS SafetyGuard — AI 위험도 통합 플랫폼")
        self.setWindowIcon(QIcon(resource_path("assets/kd_safety_guard_icon.png")))
        self.resize(1600, 950)

        # 엔진 생성
        self.hazard_engine = Hazard9Engine()
        self.pipeguard_engine = PipeGuardEngine()

        # 화면 생성
        self.dashboard = DashboardView()
        self.hazard_view = Hazard9View(self.hazard_engine, parent=self)
        self.pipeguard_view = PipeGuardView(self.pipeguard_engine, parent=self)

        # ✅ WindGuard 2.0 화면 생성 (엔진과는 독립 모듈)
        self.windguard_view = WindGuardView(parent=self)

        # ✅ FinalRiskView 생성 인자 이름 정리
        self.final_view = FinalRiskView(
            hazard_engine=self.hazard_engine,
            pipeguard_engine=self.pipeguard_engine,
            parent=self,
        )

        # 리포트 입력 화면
        self.report_input = ReportInputView(parent=self)

        # 리포트 히스토리 화면
        self.report_history = ReportHistoryView(parent=self)

        # 사이드바
        self.sidebar = Sidebar(self)

        # 레이아웃
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.dashboard)

        self.current_page = self.dashboard
        self.setCentralWidget(container)

    # -------------------------
    # Getter (FinalRiskView에서 필요하면 사용 가능)
    # -------------------------
    def get_hazard9_score(self):
        try:
            return self.hazard_engine.score
        except Exception:
            return 0

    def get_pipeguard_result(self):
        try:
            return self.pipeguard_view.result
        except Exception:
            return None

    # -------------------------
    # 화면 전환 공통 함수
    # -------------------------
    def _switch_page(self, new_widget):
        layout = self.centralWidget().layout()
        layout.replaceWidget(self.current_page, new_widget)
        self.current_page.hide()
        new_widget.show()
        self.current_page = new_widget

    # -------------------------
    # 메뉴 이동
    # -------------------------
    def show_hazard(self):
        self._switch_page(self.hazard_view)

    def show_pipeguard(self):
        self._switch_page(self.pipeguard_view)

    def show_windguard(self):
        """사이드바 'WindGuard 2.0' 클릭 시 호출"""
        self._switch_page(self.windguard_view)

    def show_final(self):
        # FinalRiskView 데이터 갱신 후 화면 전환
        self.final_view.reload_data()
        self._switch_page(self.final_view)

    def show_info(self):
        self._switch_page(self.dashboard)

    # -------------------------
    # FinalRiskView → ReportInputView 이동
    # -------------------------
    def go_final_risk(self):
        print("▶ go_final_risk() — FinalRiskView 갱신")
        self.final_view.reload_data()
        self._switch_page(self.final_view)

    def go_report_input(self):
        print("▶ go_report_input() — 리포트 입력 화면 이동")
        self._switch_page(self.report_input)

    def show_report_input(self):
        self._switch_page(self.report_input)

    # -------------------------
    # Report History View 이동
    # -------------------------
    def show_report_history(self):
        print("▶ show_report_history() — ReportHistory 화면 이동")
        self.report_history.reload_history()
        self._switch_page(self.report_history)


# ================================
# 실행부
# ================================
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 전역 아이콘도 설정 (메시지박스 등에서 사용)
    app.setWindowIcon(QIcon(resource_path("assets/kd_safety_guard_icon.png")))

    # KDENS 디자인 적용
    app.setStyleSheet(
        """
        QMainWindow { background-color: #003B70; }
        QPushButton {
            background-color: #003B70;
            color: white;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 14px;
        }
        QPushButton:hover { background-color: #25C48F; }
        """
    )

    # Splash Screen
    splash = KdensSplashScreen(resource_path("assets/kdens_splash.png"))
    splash.show()

    def show_main_window():
        """
        ▷ 첫 실행 시: TermsDialog로 회사명/사용자/약관 동의 + install 로그
        ▷ 이후 실행 시: startup 로그만 전송
        ▷ 예외 발생 시: Documents\\KDENS_SafetyGuard\\error.log 에 저장 후 안내 메시지
        """
        try:
            lic = ensure_license(parent=None)
            if lic is None:
                # 약관 동의하지 않으면 프로그램 종료
                QApplication.quit()
                return

            win = MainWindow()
            win.show()

            # ✅ 업데이트 체크 중 예외는 앱이 죽지 않도록 별도 처리
            try:
                check_for_update(win)
            except Exception:
                home = Path(os.path.expanduser("~"))
                log_dir = home / "Documents" / "KDENS_SafetyGuard"
                log_dir.mkdir(parents=True, exist_ok=True)
                with open(log_dir / "error.log", "a", encoding="utf-8") as f:
                    f.write(f"\n[{datetime.now()}] check_for_update error:\n")
                    traceback.print_exc(file=f)

        except Exception:
            # 메인 윈도우 생성 과정에서 치명적 오류 발생 시 로그 남기고 종료
            home = Path(os.path.expanduser("~"))
            log_dir = home / "Documents" / "KDENS_SafetyGuard"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "error.log"

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now()}] FATAL ERROR in show_main_window:\n")
                traceback.print_exc(file=f)

            QMessageBox.critical(
                None,
                "프로그램 오류",
                "KDENS SafetyGuard 실행 중 예기치 않은 오류가 발생했습니다.\n"
                f"자세한 내용은 다음 로그 파일을 확인해 주세요.\n\n{log_path}",
            )
            QApplication.quit()

    splash.start(show_main_window)
    sys.exit(app.exec())
