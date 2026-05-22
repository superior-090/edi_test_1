import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'design_system.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _prnController = TextEditingController();
  final _branchController = TextEditingController(text: 'CSE');
  final _divisionController = TextEditingController(text: 'A');
  final _semesterController = TextEditingController(text: '1');
  final _yearController = TextEditingController(text: '1');
  bool _saving = false;
  bool _prefilled = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_prefilled) return;
    _prefilled = true;
    final user = context.read<AppState>().user;
    _nameController.text = (user?['full_name'] ?? '').toString();
    _prnController.text = (user?['prn'] ?? '').toString();
    _branchController.text = (user?['branch'] ?? _branchController.text).toString();
    _divisionController.text = (user?['division'] ?? _divisionController.text).toString();
    _semesterController.text = (user?['semester'] ?? _semesterController.text).toString();
    _yearController.text = (user?['year'] ?? _yearController.text).toString();
  }

  @override
  void dispose() {
    _nameController.dispose();
    _prnController.dispose();
    _branchController.dispose();
    _divisionController.dispose();
    _semesterController.dispose();
    _yearController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _saving = true);
    try {
      final state = context.read<AppState>();
      await state.updateProfile(
        fullName: _nameController.text.trim(),
        prn: _prnController.text.trim(),
        branch: _branchController.text.trim(),
        division: _divisionController.text.trim(),
        semester: _semesterController.text.trim(),
        year: _yearController.text.trim(),
      );
      if (!mounted) return;
      Navigator.pushReplacementNamed(context, '/student_home');
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Profile save failed: $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Complete Student Profile')),
      body: AiGradientBackground(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                const GlassCard(
                  padding: EdgeInsets.all(18),
                  child: Row(
                    children: [
                      Icon(Icons.badge, color: AiColors.cyan),
                      SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          'Profile details are required before joining any exam.',
                          style: TextStyle(fontWeight: FontWeight.w800),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                GlassCard(
                  child: Form(
                    key: _formKey,
                    child: Column(
                      children: [
                        _Field(controller: _nameController, label: 'Full name', icon: Icons.person),
                        _Field(controller: _prnController, label: 'PRN', icon: Icons.confirmation_number),
                        Row(
                          children: [
                            Expanded(child: _Field(controller: _branchController, label: 'Branch', icon: Icons.account_tree)),
                            const SizedBox(width: 12),
                            Expanded(child: _Field(controller: _divisionController, label: 'Division', icon: Icons.groups)),
                          ],
                        ),
                        Row(
                          children: [
                            Expanded(child: _Field(controller: _semesterController, label: 'Semester', icon: Icons.school)),
                            const SizedBox(width: 12),
                            Expanded(child: _Field(controller: _yearController, label: 'Year', icon: Icons.calendar_month)),
                          ],
                        ),
                        const SizedBox(height: 10),
                        Align(
                          alignment: Alignment.centerRight,
                          child: GradientButton(
                            onPressed: _saving ? null : _submit,
                            icon: Icons.save,
                            label: _saving ? 'Saving' : 'Save profile',
                            loading: _saving,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({
    required this.controller,
    required this.label,
    required this.icon,
  });

  final TextEditingController controller;
  final String label;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: TextFormField(
        controller: controller,
        decoration: InputDecoration(labelText: label, prefixIcon: Icon(icon)),
        validator: (value) => value == null || value.trim().isEmpty ? 'Required' : null,
      ),
    );
  }
}
