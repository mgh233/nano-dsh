# Preserve the minimal dynamic Plugin lifecycle

nano-dsh keeps dependency-driven Plugin activation, Effect cleanup, and
reactivation after a required Service returns. This behavior distinguishes the
runtime from a startup-only dependency injector. The first version excludes
configuration hot reload, transactional rollback, and the other production
lifecycle features of Cordis. A Fiber uses the explicit states `PENDING`,
`LOADING`, and `ACTIVE`. Unloading returns it to `PENDING`. Boot uses an
internal `assert` if an enabled Fiber remains `PENDING` after loading.
The Context accepts only one active Provider for each Service name. Replacing a
Provider requires unloading the old Provider before loading the new one.
`ctx.provide()` and `ctx.effect()` bind resources to the currently loading
Fiber. Unloading that Fiber runs its disposers in reverse registration order,
which automatically removes Service, Tool, and AgentFactory registrations. A
disposer failure propagates directly from its source.
Bundle order controls Fiber creation only. A Consumer can load before its
Providers, remain `PENDING`, and activate when its final required Service
appears. The Loader does not topologically sort Plugins.
