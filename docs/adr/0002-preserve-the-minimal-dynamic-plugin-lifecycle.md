# Preserve the minimal dynamic Plugin lifecycle

nano-dsh keeps dependency-driven Plugin activation, Effect cleanup, and
reactivation after a required Service returns. This behavior distinguishes the
runtime from a startup-only dependency injector. The first version excludes
configuration hot reload, transactional rollback, and the other production
lifecycle features of Cordis. A Fiber uses the explicit states `PENDING`,
`LOADING`, `ACTIVE`, `UNLOADING`, `FAILED`, and `DISPOSED`. Boot fails visibly
if any enabled Fiber remains `PENDING` after all Plugin Specifications load.
The Context accepts only one active Provider for each Service name. Replacing a
Provider requires unloading the old Provider before loading the new one.
`ctx.provide()` and `ctx.effect()` bind resources to the currently loading
Fiber. Unloading that Fiber runs its disposers in reverse registration order,
which automatically removes Service, Tool, and AgentFactory registrations.
Bundle order controls Fiber creation only. A Consumer can load before its
Providers, remain `PENDING`, and activate when its final required Service
appears. The Loader does not topologically sort Plugins.
