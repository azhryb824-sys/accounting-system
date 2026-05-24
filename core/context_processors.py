from .access import user_accessible_branches


def company_branch_switcher(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    branches = user_accessible_branches(user).order_by("company__name", "name")
    companies = []
    seen = set()
    for branch in branches:
        if branch.company_id not in seen:
            companies.append(branch.company)
            seen.add(branch.company_id)
    return {
        "switcher_companies": companies,
        "switcher_branches": branches,
    }
