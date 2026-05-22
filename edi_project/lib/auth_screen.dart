import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app_state.dart';
import 'design_system.dart';

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController(text: 'candidate');
  final _passwordController = TextEditingController(text: 'student123');
  final _sideCameraController = TextEditingController();
  bool _rememberMe = true;
  bool _loading = false;
  bool _obscure = true;
  String _role = 'student';
  String? _error;
  bool _prefilledSideCamera = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_prefilledSideCamera) {
      _sideCameraController.text = context.read<AppState>().sideCameraUrl;
      _prefilledSideCamera = true;
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      await context.read<AppState>().login(
        username: _usernameController.text.trim(),
        password: _passwordController.text,
        role: _role,
        rememberMe: _rememberMe,
        sideCameraUrl: _role == 'student'
            ? _sideCameraController.text.trim()
            : '',
      );
      if (!mounted) return;
      final state = context.read<AppState>();
      Navigator.pushReplacementNamed(
        context,
        state.isTeacher
            ? '/teacher_home'
            : state.isProctor
            ? '/admin_home'
            : '/student_home',
      );
    } catch (error) {
      if (mounted) {
        setState(
          () => _error = error.toString().replaceFirst('Exception: ', ''),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: AiGradientBackground(
        child: SafeArea(
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1180),
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(22),
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final wide = constraints.maxWidth >= 900;
                    return Flex(
                      direction: wide ? Axis.horizontal : Axis.vertical,
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        if (wide)
                          Expanded(
                            flex: 6,
                            child: Padding(
                              padding: const EdgeInsets.only(right: 28),
                              child: const _AuthHero(),
                            ),
                          )
                        else
                          const Padding(
                            padding: EdgeInsets.only(bottom: 22),
                            child: _AuthHero(),
                          ),
                        if (wide)
                          Expanded(
                            flex: 4,
                            child: GlassCard(
                              padding: const EdgeInsets.all(24),
                              borderColor: AiColors.cyan.withValues(alpha: 0.28),
                              child: _AuthForm(
                                formKey: _formKey,
                                usernameController: _usernameController,
                                passwordController: _passwordController,
                                sideCameraController: _sideCameraController,
                                role: _role,
                                rememberMe: _rememberMe,
                                loading: _loading,
                                obscure: _obscure,
                                error: _error,
                                onRoleChanged: _setRole,
                                onRememberChanged: (value) =>
                                    setState(() => _rememberMe = value),
                                onObscureChanged: () =>
                                    setState(() => _obscure = !_obscure),
                                onSubmit: _submit,
                              ),
                            ),
                          )
                        else
                          GlassCard(
                            padding: const EdgeInsets.all(24),
                            borderColor: AiColors.cyan.withValues(alpha: 0.28),
                            child: _AuthForm(
                              formKey: _formKey,
                              usernameController: _usernameController,
                              passwordController: _passwordController,
                              sideCameraController: _sideCameraController,
                              role: _role,
                              rememberMe: _rememberMe,
                              loading: _loading,
                              obscure: _obscure,
                              error: _error,
                              onRoleChanged: _setRole,
                              onRememberChanged: (value) =>
                                  setState(() => _rememberMe = value),
                              onObscureChanged: () =>
                                  setState(() => _obscure = !_obscure),
                              onSubmit: _submit,
                            ),
                          ),
                      ],
                    );
                  },
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  void _setRole(String role) {
    setState(() {
      _role = role;
      if (role == 'teacher') {
        _usernameController.text = 'teacher';
        _passwordController.text = 'teacher123';
      } else if (role == 'proctor') {
        _usernameController.text = 'proctor';
        _passwordController.text = 'proctor123';
      } else if (role == 'admin') {
        _usernameController.text = 'admin';
        _passwordController.text = 'admin123';
      } else {
        _usernameController.text = 'candidate';
        _passwordController.text = 'student123';
      }
    });
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _sideCameraController.dispose();
    super.dispose();
  }
}

class _AuthHero extends StatelessWidget {
  const _AuthHero();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const StatusBadge(label: 'Realtime AI proctoring', color: AiColors.cyan, pulse: true),
        const SizedBox(height: 18),
        Text(
          'AI exam control center for secure digital assessments.',
          style: Theme.of(context).textTheme.displaySmall?.copyWith(
                fontWeight: FontWeight.w900,
                height: 1.02,
              ),
        ),
        const SizedBox(height: 16),
        const Text(
          'Monitor candidates, manage exams, review suspicious activity, and keep assessment integrity visible from one premium operations console.',
          style: TextStyle(color: Colors.white70, fontSize: 16, height: 1.55),
        ),
        const SizedBox(height: 22),
        LayoutBuilder(
          builder: (context, constraints) {
            final narrow = constraints.maxWidth < 680;
            return Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                SizedBox(
                  width: narrow ? constraints.maxWidth : 190,
                  child: const MetricTile(
                    icon: Icons.visibility,
                    label: 'Camera streams',
                    value: '2x',
                    caption: 'front + side',
                    color: AiColors.cyan,
                  ),
                ),
                SizedBox(
                  width: narrow ? constraints.maxWidth : 190,
                  child: const MetricTile(
                    icon: Icons.radar,
                    label: 'AI risk engine',
                    value: 'Live',
                    caption: 'pulse detection',
                    color: AiColors.purple,
                  ),
                ),
                SizedBox(
                  width: narrow ? constraints.maxWidth : 190,
                  child: const MetricTile(
                    icon: Icons.warning_amber,
                    label: 'Alerts',
                    value: 'Instant',
                    caption: 'timeline logs',
                    color: AiColors.red,
                  ),
                ),
              ],
            );
          },
        ),
        const SizedBox(height: 22),
        GlassCard(
          padding: const EdgeInsets.all(16),
          child: SizedBox(
            height: 150,
            child: Row(
              children: [
                Expanded(
                  child: MiniBars(
                    values: const [0.28, 0.44, 0.36, 0.72, 0.58, 0.82, 0.64, 0.9],
                    color: AiColors.cyan,
                  ),
                ),
                const SizedBox(width: 16),
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      StatusBadge(label: 'Monitoring stable', color: AiColors.green, pulse: true),
                      SizedBox(height: 12),
                      Text('Live confidence, risk score, camera health, and candidate session state stay visible at a glance.'),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 14),
        const _ReviewStrip(),
      ],
    );
  }
}

class _ReviewStrip extends StatelessWidget {
  const _ReviewStrip();

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: const [
        _ReviewCard(
          quote: 'Clean monitoring view with instant risk context.',
          name: 'Exam Coordinator',
        ),
        _ReviewCard(
          quote: 'Teacher setup and proctor control finally feel connected.',
          name: 'Faculty Admin',
        ),
      ],
    );
  }
}

class _ReviewCard extends StatelessWidget {
  const _ReviewCard({required this.quote, required this.name});

  final String quote;
  final String name;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 260,
      child: GlassCard(
        padding: const EdgeInsets.all(14),
        borderColor: AiColors.purple.withValues(alpha: 0.2),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(quote, style: const TextStyle(color: Colors.white70, height: 1.35)),
            const SizedBox(height: 10),
            Text(name, style: const TextStyle(color: AiColors.cyan, fontWeight: FontWeight.w800)),
          ],
        ),
      ),
    );
  }
}

class _AuthForm extends StatelessWidget {
  const _AuthForm({
    required this.formKey,
    required this.usernameController,
    required this.passwordController,
    required this.sideCameraController,
    required this.role,
    required this.rememberMe,
    required this.loading,
    required this.obscure,
    required this.error,
    required this.onRoleChanged,
    required this.onRememberChanged,
    required this.onObscureChanged,
    required this.onSubmit,
  });

  final GlobalKey<FormState> formKey;
  final TextEditingController usernameController;
  final TextEditingController passwordController;
  final TextEditingController sideCameraController;
  final String role;
  final bool rememberMe;
  final bool loading;
  final bool obscure;
  final String? error;
  final ValueChanged<String> onRoleChanged;
  final ValueChanged<bool> onRememberChanged;
  final VoidCallback onObscureChanged;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    return Form(
      key: formKey,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(colors: [AiColors.cyan, AiColors.purple]),
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [
                    BoxShadow(color: AiColors.cyan.withValues(alpha: 0.28), blurRadius: 22),
                  ],
                ),
                child: const Icon(Icons.security_rounded, color: Color(0xFF061018)),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Secure Access',
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w900),
                    ),
                    const Text('AI exam monitoring workspace', style: TextStyle(color: Colors.white60)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 22),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'student', label: Text('Student'), icon: Icon(Icons.person)),
              ButtonSegment(value: 'teacher', label: Text('Teacher'), icon: Icon(Icons.co_present)),
              ButtonSegment(value: 'proctor', label: Text('Proctor'), icon: Icon(Icons.admin_panel_settings)),
              ButtonSegment(value: 'admin', label: Text('Admin'), icon: Icon(Icons.shield)),
            ],
            selected: {role},
            onSelectionChanged: (value) => onRoleChanged(value.first),
          ),
          const SizedBox(height: 18),
          TextFormField(
            controller: usernameController,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(
              labelText: 'Email or username',
              prefixIcon: Icon(Icons.alternate_email),
            ),
            validator: (value) => value == null || value.trim().length < 3 ? 'Enter a valid username' : null,
          ),
          const SizedBox(height: 14),
          TextFormField(
            controller: passwordController,
            obscureText: obscure,
            onFieldSubmitted: (_) => onSubmit(),
            decoration: InputDecoration(
              labelText: 'Password',
              prefixIcon: const Icon(Icons.lock_outline),
              suffixIcon: IconButton(
                onPressed: onObscureChanged,
                icon: Icon(obscure ? Icons.visibility : Icons.visibility_off),
              ),
            ),
            validator: (value) => value == null || value.length < 6 ? 'Password must be at least 6 characters' : null,
          ),
          if (role == 'student') ...[
            const SizedBox(height: 14),
            TextFormField(
              controller: sideCameraController,
              decoration: const InputDecoration(
                labelText: 'Side camera IP or stream URL',
                hintText: '192.168.0.103:8080',
                prefixIcon: Icon(Icons.settings_input_antenna),
              ),
              validator: (value) => value == null || value.trim().isEmpty ? 'Enter your side camera IP' : null,
            ),
          ],
          const SizedBox(height: 8),
          Row(
            children: [
              Checkbox(value: rememberMe, onChanged: (value) => onRememberChanged(value ?? false)),
              const Text('Remember me'),
              const Spacer(),
              TextButton(onPressed: () {}, child: const Text('Forgot password')),
            ],
          ),
          if (error != null) ...[
            const SizedBox(height: 6),
            _AlertText(message: error!),
          ],
          const SizedBox(height: 16),
          GradientButton(
            onPressed: loading ? null : onSubmit,
            icon: Icons.login,
            label: loading ? 'Authenticating' : 'Sign in',
            loading: loading,
          ),
          const SizedBox(height: 14),
          Text(
            'Demo: candidate/student123, teacher/teacher123, proctor/proctor123',
            textAlign: TextAlign.center,
            style: TextStyle(
              color: Theme.of(context).colorScheme.onSurface.withValues(
                    alpha: 0.45,
                  ),
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }
}

class _AlertText extends StatelessWidget {
  const _AlertText({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.red.withValues(alpha: 0.12),
        border: Border.all(color: Colors.redAccent.withValues(alpha: 0.45)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, color: Colors.redAccent),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(color: Colors.redAccent),
            ),
          ),
        ],
      ),
    );
  }
}
