"""Non-ASCII fixture: identifiers and text outside ASCII, on purpose."""


def calculer_montant(lignes, taux_tva):
    """Montant total, TVA comprise — «déjà arrondi» à deux décimales."""
    brut = sum(ligne["prix"] * ligne["quantité"] for ligne in lignes)
    return round(brut * (1 + taux_tva), 2)


def résumé_français(client):
    """Renvoie un résumé lisible pour l'entête de la facture."""
    return f"Facture pour {client} — merci de votre confiance ★"
