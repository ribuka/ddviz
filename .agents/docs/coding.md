# Coding

Every change must leave the code it touches no harder to change than before.

These rules apply to every language and to tests. Each language's file adds what is specific to that language.

## Before writing code

- Search for code that already does the same thing (`git grep` for the operation, not only the name). Reuse or extend it instead of writing another copy.
- Choose the module for new code by the responsibility stated at the top of each module. If no module's statement covers the new code without adding "and", create a focused module.

## Scope of a change

- Keep the change to what the task needs. The following are part of the task, not extra work:
  - Extracting logic the change would otherwise duplicate. Extract when the copies hold the same knowledge and would change for the same reason, not because they look alike.
  - Deleting functions, parameters, and branches the change made unused.
  - Updating a module's responsibility statement when its responsibility changes.
- Put such refactoring in its own `refactor:` commit before the change that needs it, and keep behavior the same in that commit.
- Do NOT refactor code the task does not touch. List debt noticed there in the PR description under "気づいた負債" instead.

## Modules

- Keep one primary responsibility per module, stated at its top.
- NEVER append a distinct responsibility to an existing module; create a focused module or package instead.
- Import names from the module that defines them. NEVER add modules that only re-export. When refactoring changes an import path, update every reference.
- NEVER introduce circular imports or generic catch-all modules such as `utils.py` or `helpers.js`.
- Size is a reason to look, not a reason to split. NEVER split modules based on line count alone.

## Functions and classes

- For a variant of existing behavior, pass the difference as a value or a callable instead of copying the function.
- Prefer a separate function over a boolean parameter that switches what a function does.
- Do not grow a function by adding another mode branch; split it into stages first (as a `refactor:` commit).
- Functions are held to complexity limits (cyclomatic complexity, branches, statements; each language's file says where the values are and how they are checked). NEVER raise the limits or add a `noqa` for them; split the function instead.
- Existing `noqa` marks for these limits are debt from before the limits. Do not make such a function longer or more complex; when a change brings it under the limits, remove the mark (a stale mark fails the check).

## Tests

- The rules above apply to tests too. Before adding a test helper, search the shared test setup and the test file you are editing.
- Organize tests by responsibility, and share setup only as widely as the tests that use it.
