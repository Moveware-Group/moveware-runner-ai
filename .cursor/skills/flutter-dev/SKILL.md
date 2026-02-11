---
name: flutter-dev
description: Flutter/Dart mobile app development with Material Design. Use when building Flutter apps, working with Dart, or when the user mentions Flutter, mobile app, or cross-platform development.
---

# Flutter Developer

## Project Structure

Follow Flutter/Dart conventions:

```
lib/
├── main.dart              # App entry point
├── app.dart                # MaterialApp configuration
├── core/                   # Shared utilities, constants
├── features/               # Feature-based organization
│   ├── auth/
│   │   ├── data/
│   │   ├── domain/
│   │   └── presentation/
│   └── home/
├── shared/                 # Shared widgets, theme
│   ├── widgets/
│   └── theme/
└── routes/                 # Navigation/routing
```

## pubspec.yaml Essentials

```yaml
name: my_app
description: App description
version: 1.0.0+1

environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter
  # Add packages here

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.0

flutter:
  uses-material-design: true
  assets:
    - assets/images/
  fonts:
    - family: CustomFont
      fonts:
        - asset: assets/fonts/CustomFont-Regular.ttf
```

## Widget Patterns

### Stateless vs Stateful

```dart
// StatelessWidget - for static UI
class MyCard extends StatelessWidget {
  final String title;
  const MyCard({super.key, required this.title});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Text(title),
      ),
    );
  }
}

// StatefulWidget - for dynamic UI
class Counter extends StatefulWidget {
  const Counter({super.key});

  @override
  State<Counter> createState() => _CounterState();
}

class _CounterState extends State<Counter> {
  int _count = 0;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text('Count: $_count'),
        ElevatedButton(
          onPressed: () => setState(() => _count++),
          child: const Text('Increment'),
        ),
      ],
    );
  }
}
```

## State Management

### Provider (Recommended)

```dart
// Provider
Provider(
  create: (_) => MyViewModel(),
  child: MyScreen(),
)

// Consumer
Consumer<MyViewModel>(
  builder: (context, viewModel, child) {
    return Text(viewModel.value);
  },
)
```

### setState for local state

Use `setState` for widget-local state. Use Provider/Riverpod for app-wide state.

## Styling with Theme

```dart
// Use theme consistently
Theme.of(context).colorScheme.primary
Theme.of(context).textTheme.titleLarge
Theme.of(context).elevatedButtonTheme
```

## Navigation

```dart
// Navigate
Navigator.push(context, MaterialPageRoute(builder: (_) => DetailPage()));

// Named routes
Navigator.pushNamed(context, '/detail', arguments: id);

// GoRouter (if used)
context.go('/home');
```

## API/Async Patterns

```dart
Future<List<Item>> fetchItems() async {
  final response = await http.get(Uri.parse('$baseUrl/items'));
  if (response.statusCode == 200) {
    return parseItems(response.body);
  }
  throw Exception('Failed to load');
}

// In widget
FutureBuilder<List<Item>>(
  future: fetchItems(),
  builder: (context, snapshot) {
    if (snapshot.hasData) return ListView(...);
    if (snapshot.hasError) return ErrorWidget(snapshot.error!);
    return const CircularProgressIndicator();
  },
)
```

## Build Verification

- Run `flutter pub get` before build
- Run `flutter analyze` for static analysis
- Run `flutter test` for unit tests
- Build: `flutter build apk` or `flutter build ios`

## Common Conventions

- Use `const` constructors where possible
- Null safety: use `?` and `!` appropriately
- Prefer `final` over `var`
- Use `Key` for widgets in lists
- Extract widgets when >50 lines or reusable
