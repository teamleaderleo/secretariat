export function sendNativeRequest(runtime, hostName, request) {
  return new Promise((resolve, reject) => {
    runtime.sendNativeMessage(hostName, request, (response) => {
      const lastError = runtime.lastError;
      if (lastError && typeof lastError.message === "string") {
        reject({ message: lastError.message });
        return;
      }
      if (response === undefined) {
        reject({ message: "Native messaging host returned no response." });
        return;
      }
      resolve(response);
    });
  });
}
