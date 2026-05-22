import 'dart:js_interop';

void enableExamCopyGuard() {
  _enableExamCopyGuard();
}

void disableExamCopyGuard() {
  _disableExamCopyGuard();
}

@JS('proctorExamGuardEnable')
external void _enableExamCopyGuard();

@JS('proctorExamGuardDisable')
external void _disableExamCopyGuard();
