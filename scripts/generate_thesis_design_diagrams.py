from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "thesis" / "src" / "img" / "carvaluator"


def add_box(ax, x, y, width, height, title, lines, color):
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.025",
        linewidth=2,
        edgecolor=color,
        facecolor=f"{color}18",
    )
    ax.add_patch(patch)
    ax.text(x + width / 2, y + height - 0.06, title, ha="center", va="top", fontsize=13, fontweight="bold")
    ax.text(x + 0.035, y + height - 0.14, "\n".join(lines), ha="left", va="top", fontsize=10, linespacing=1.35)
    return patch


def arrow(ax, start, end, label=None, offset=0.0):
    patch = FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16, linewidth=1.8, color="#334155")
    ax.add_patch(patch)
    if label:
        x = (start[0] + end[0]) / 2
        y = (start[1] + end[1]) / 2 + offset
        ax.text(x, y, label, ha="center", va="center", fontsize=9, color="#1f2937", backgroundcolor="white")


def execution_sequence():
    fig, ax = plt.subplots(figsize=(16, 8.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("Diagrama de secventa pentru analiza unui anunt", fontsize=22, fontweight="bold", pad=20)

    actors = [
        ("Utilizator", 0.08, "#0891b2"),
        ("Frontend", 0.25, "#0f766e"),
        ("FastAPI", 0.43, "#2563eb"),
        ("Scraper", 0.61, "#ca8a04"),
        ("Modele ML", 0.78, "#7c3aed"),
        ("SQLite", 0.93, "#dc2626"),
    ]
    for name, x, color in actors:
        ax.text(x, 0.91, name, ha="center", va="center", fontsize=12, fontweight="bold", color=color)
        ax.plot([x, x], [0.1, 0.86], linestyle="--", linewidth=1.2, color="#94a3b8")

    messages = [
        (0.82, 0.08, 0.25, "1. Introduce link + optiuni"),
        (0.73, 0.25, 0.43, "2. POST /predict"),
        (0.64, 0.43, 0.93, "3. Verifica sesiunea"),
        (0.55, 0.43, 0.61, "4. Extrage anuntul"),
        (0.46, 0.61, 0.43, "5. Date brute"),
        (0.37, 0.43, 0.78, "6. Normalizeaza si prezice"),
        (0.28, 0.78, 0.43, "7. Estimari pe modele"),
        (0.19, 0.43, 0.93, "8. Salveaza istoricul"),
        (0.12, 0.43, 0.25, "9. JSON: verdict + similare"),
    ]
    for y, x1, x2, label in messages:
        direction = 1 if x2 > x1 else -1
        arrow(ax, (x1 + 0.012 * direction, y), (x2 - 0.012 * direction, y), label, 0.024)

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "execution_sequence.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def database_schema():
    fig, ax = plt.subplots(figsize=(15, 8.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("Schema relationala a bazei de date SQLite", fontsize=22, fontweight="bold", pad=20)

    add_box(
        ax,
        0.06,
        0.31,
        0.25,
        0.48,
        "users",
        [
            "PK  id : INTEGER",
            "UQ  email : TEXT",
            "UQ  username : TEXT",
            "    password_hash : TEXT",
            "    created_at : TEXT",
        ],
        "#0891b2",
    )
    add_box(
        ax,
        0.39,
        0.54,
        0.25,
        0.32,
        "sessions",
        [
            "PK  token : TEXT",
            "FK  user_id : INTEGER",
            "    expires_at : TEXT",
            "    created_at : TEXT",
        ],
        "#7c3aed",
    )
    add_box(
        ax,
        0.69,
        0.18,
        0.27,
        0.68,
        "prediction_history",
        [
            "PK  id : INTEGER",
            "FK  user_id : INTEGER",
            "    source : TEXT",
            "    url : TEXT",
            "    title : TEXT",
            "    image_url : TEXT",
            "    actual_price_eur : REAL",
            "    predicted_price_eur : REAL",
            "    verdict : TEXT",
            "    model_name : TEXT",
            "    delta_percent : REAL",
            "    prediction_json : TEXT",
            "    created_at : TEXT",
        ],
        "#dc2626",
    )

    arrow(ax, (0.31, 0.66), (0.39, 0.70), "1 : N", 0.035)
    arrow(ax, (0.31, 0.43), (0.69, 0.43), "1 : N", 0.035)
    ax.text(
        0.5,
        0.08,
        "Stergerea unui utilizator elimina sesiunile si istoricul asociat prin ON DELETE CASCADE.",
        ha="center",
        fontsize=11,
        color="#334155",
    )

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "database_schema.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def route_matrix():
    fig, ax = plt.subplots(figsize=(13, 8.5))
    ax.set_xlim(-1.4, 3.15)
    ax.set_ylim(-0.8, 3.95)
    ax.axis("off")
    ax.set_title("Matricea rutelor", fontsize=22, fontweight="bold", pad=18)
    ax.text(
        1.45,
        -0.5,
        "Cati utilizatori folosesc functionalitatea",
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        color="#475569",
    )
    ax.text(
        -1.14,
        1.45,
        "Frecventa utilizarii de catre un utilizator",
        ha="center",
        va="center",
        rotation=90,
        fontsize=12,
        fontweight="bold",
        color="#475569",
    )

    columns = ["Putini", "Multi", "Toti"]
    rows = ["Frecvent", "Ocazional", "Rar"]
    cells = {
        (0, 2): "Verificarea\nunui anunt",
        (1, 1): "Consultarea\nistoricului",
        (1, 2): "Autentificare",
        (2, 0): "Pagina de\nexplicatii",
        (2, 2): "Crearea\ncontului",
    }

    for column_index, label in enumerate(columns):
        ax.text(
            column_index + 0.47,
            -0.08,
            label,
            ha="center",
            va="top",
            fontsize=11,
            fontweight="bold",
            color="#475569",
        )

    for row_index, label in enumerate(rows):
        y = 2.35 - row_index
        ax.text(
            -0.18,
            y + 0.43,
            label,
            ha="right",
            va="center",
            fontsize=11,
            fontweight="bold",
            color="#475569",
        )
        for column_index in range(3):
            content = cells.get((row_index, column_index), "")
            usage_score = ((2 - row_index) + column_index) / 4
            facecolor = plt.get_cmap("Reds")(0.12 + usage_score * 0.72)
            patch = FancyBboxPatch(
                (column_index + 0.04, y),
                0.86,
                0.84,
                boxstyle="round,pad=0.02,rounding_size=0.1",
                linewidth=1.5,
                edgecolor="#ffffff",
                facecolor=facecolor,
            )
            ax.add_patch(patch)
            if content:
                text_color = "#ffffff" if usage_score >= 0.55 else "#7f1d1d"
                ax.text(
                    column_index + 0.47,
                    y + 0.42,
                    content,
                    ha="center",
                    va="center",
                    fontsize=11,
                    fontweight="bold",
                    color=text_color,
                    linespacing=1.25,
                )

    ax.text(
        1.45,
        3.55,
        "Nuantele mai intense indica functionalitati utilizate mai des si de mai multi utilizatori.",
        ha="center",
        fontsize=10.5,
        color="#475569",
    )

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "route_matrix.png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    execution_sequence()
    database_schema()
    route_matrix()
    print(f"Generated design diagrams in {OUTPUT_DIR}")
