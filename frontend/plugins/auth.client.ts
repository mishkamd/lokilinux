export default defineNuxtPlugin(async () => {
  await refreshAuthToken()
})
