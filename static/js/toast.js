function showToast(message) {
    const toastContainer = document.querySelector(".toast-container");
    if (!toastContainer) return;

    const toast = document.createElement("div");
    toast.className = "toast show";
    toast.innerHTML = `${message} <button class="close-btn">&times;</button>`;

    toastContainer.appendChild(toast);

    // Close button event
    toast.querySelector(".close-btn").addEventListener("click", () => {
        toast.style.animation = "slideOut 0.3s forwards";
        setTimeout(() => toast.remove(), 300);
    });

    // Auto-hide after 4 seconds
    setTimeout(() => {
        toast.style.animation = "slideOut 0.3s forwards";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}
