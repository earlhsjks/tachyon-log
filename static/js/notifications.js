function createNotification({ title, message, theme, positionClass, showDuration }) {
    let container = document.getElementById("notification-container");

    // Create Notification Element
    let notification = document.createElement("div");
    notification.classList.add("ncf", theme, positionClass);
    
    // Title & Message
    notification.innerHTML = `
        <strong class="ncf-title">${title}</strong>
        <span class="ncf-message">${message}</span>
        <button onclick="this.parentElement.remove()">×</button>
    `;

    // Append Notification
    container.appendChild(notification);

    // Auto Remove Notification
    setTimeout(() => {
        notification.style.opacity = "0";
        setTimeout(() => notification.remove(), 500);
    }, showDuration);
}
