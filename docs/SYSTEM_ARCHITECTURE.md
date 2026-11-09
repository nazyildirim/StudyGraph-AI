## 8. Architecture Decision — Why Modular Layered Architecture?

### Selected Architecture

StudyGraph AI adopts a **Modular Layered Architecture**, guided by Clean Architecture principles, with a modular monolithic FastAPI backend and a separate React frontend.

The system is organized into four conceptual layers:

1. **Presentation Layer:** React-based student and instructor interfaces.
2. **Application Layer:** FastAPI endpoints, application services, and use-case orchestration.
3. **Domain Layer:** Learning outcome graphs, mastery calculations, prerequisite validation, and recommendation rules.
4. **Infrastructure Layer:** PostgreSQL persistence, repository implementations, and external RAG/LLM integrations.

### Reasons for Selection

- **Separation of Concerns:** Each layer has a distinct responsibility.
- **Maintainability:** Changes to the user interface, algorithms, or persistence logic can be managed independently where interfaces remain stable.
- **Testability:** Core learning algorithms can be tested without requiring a running database or frontend.
- **Low Coupling:** Interfaces and dependency injection reduce direct dependencies on infrastructure implementations.
- **Team Collaboration:** Three developers can work on separate modules with fewer integration conflicts.
- **Extensibility:** New recommendation strategies and AI providers can be integrated through defined interfaces.

### Why Not Microservices?

Microservices would introduce additional deployment, communication, monitoring, and distributed-system complexity.

For a three-person academic project, a modular monolithic backend provides a simpler development and testing environment while preserving clear module boundaries.

### SOLID and Design Patterns

The architecture is intended to support SOLID principles, particularly the Single Responsibility Principle and Dependency Inversion Principle.

Planned patterns include:

- **Repository Pattern** for data access abstraction.
- **Strategy Pattern** for interchangeable recommendation algorithms.
- **Dependency Injection** for connecting services to implementations.

### Decision Status

**Proposed — pending implementation and validation.**

This decision will be revisited if project requirements or technical constraints change.
