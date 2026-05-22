import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'profile_screen.dart';
import 'auth_screen.dart';
import 'student_panel.dart';
import 'admin_panel.dart';
import 'design_system.dart';
import 'teacher_dashboard.dart';

void main() {
  runApp(const ProctorSystemApp());
}

class ProctorSystemApp extends StatelessWidget {
  const ProctorSystemApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => AppState()..bootstrap(),
      child: MaterialApp(
        title: 'ProctorAI',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          brightness: Brightness.dark,
          fontFamily: 'Roboto',
          colorScheme: ColorScheme.fromSeed(
            seedColor: AiColors.cyan,
            brightness: Brightness.dark,
            surface: AiColors.panelStrong,
            primary: AiColors.cyan,
            secondary: AiColors.purple,
            error: AiColors.red,
          ),
          scaffoldBackgroundColor: AiColors.bg0,
          appBarTheme: const AppBarTheme(
            backgroundColor: Color(0xCC090D18),
            foregroundColor: Colors.white,
            elevation: 0,
            centerTitle: false,
            titleTextStyle: TextStyle(
              color: Colors.white,
              fontSize: 20,
              fontWeight: FontWeight.w900,
            ),
          ),
          cardTheme: CardThemeData(
            color: AiColors.panel,
            elevation: 0,
            margin: EdgeInsets.zero,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(22),
              side: const BorderSide(color: AiColors.border),
            ),
          ),
          inputDecorationTheme: InputDecorationTheme(
            filled: true,
            fillColor: const Color(0xAA111827),
            contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(18),
              borderSide: const BorderSide(color: AiColors.border),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(18),
              borderSide: const BorderSide(color: AiColors.border),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(18),
              borderSide: const BorderSide(color: AiColors.cyan, width: 1.4),
            ),
          ),
          filledButtonTheme: FilledButtonThemeData(
            style: FilledButton.styleFrom(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            ),
          ),
          outlinedButtonTheme: OutlinedButtonThemeData(
            style: OutlinedButton.styleFrom(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              side: const BorderSide(color: AiColors.border),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            ),
          ),
        ),
        home: const _Gate(),
        routes: {
          '/login': (context) => const AuthScreen(),
          '/student_home': (context) => const StudentPanel(),
          '/admin_home': (context) => const AdminPanel(),
          '/teacher_home': (context) => const TeacherDashboard(),
          '/profile': (context) => const ProfileScreen(),
        },
      ),
    );
  }
}

class _Gate extends StatelessWidget {
  const _Gate();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    if (!state.isReady) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!state.isAuthenticated) return const AuthScreen();
    if (state.isTeacher) return const TeacherDashboard();
    if (state.isProctor) return const AdminPanel();
    if (!state.isProfileComplete && state.isStudent) {
      // Redirect students to complete profile before accessing dashboard
      WidgetsBinding.instance.addPostFrameCallback((_) {
        Navigator.pushReplacementNamed(context, '/profile');
      });
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return const StudentPanel();
  }
}
