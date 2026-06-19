function goBack() {
  const fallback = document.body.dataset.homeUrl || "/";
  if (window.history.length > 1) {
    window.history.back();
    return;
  }
  window.location.href = fallback;
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("input.date-picker").forEach((el) => {
    if (typeof flatpickr === "undefined") return;
    flatpickr(el, {
      dateFormat: "Y-m-d",
      allowInput: true,
      disableMobile: false,
      clickOpens: true,
    });
  });
});
