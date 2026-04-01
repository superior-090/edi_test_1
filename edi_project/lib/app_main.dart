import 'package:flutter/material.dart';
import 'auth_screen.dart';
import 'student_panel.dart';
import 'admin_panel.dart';

void main() {
  runApp(const ProctorSystemApp());
}

class ProctorSystemApp extends StatelessWidget {
  const ProctorSystemApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI Proctoring Node',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: Colors.indigo,
        brightness: Brightness.light,
      ),
      initialRoute: '/',
      routes: {
        '/': (context) => const AuthScreen(),
        '/student_home': (context) => const StudentPanel(),
        '/admin_home': (context) => const AdminPanel(),
      },
    );
  }
}