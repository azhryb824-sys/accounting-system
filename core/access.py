from django.db.models import Q

from .models import Branch, Company, CompanyMembership


def user_companies(user):
    if user.is_superuser:
        return Company.objects.all()
    member_company_ids = CompanyMembership.objects.filter(user=user, is_active=True).values_list("company_id", flat=True)
    return Company.objects.filter(owner=user).union(Company.objects.filter(id__in=member_company_ids))


def user_accessible_branches(user, company=None):
    branches = Branch.objects.filter(is_active=True).select_related("company")
    if company is not None:
        branches = branches.filter(company=company)
    if user.is_superuser:
        return branches

    owned_company_ids = Company.objects.filter(owner=user).values_list("id", flat=True)
    all_branch_company_ids = CompanyMembership.objects.filter(
        user=user,
        is_active=True,
        role__branch_access="all",
    ).values_list("company_id", flat=True)
    single_branch_ids = CompanyMembership.objects.filter(
        user=user,
        is_active=True,
        role__branch_access="single",
        branch__isnull=False,
    ).values_list("branch_id", flat=True)
    return branches.filter(
        Q(company_id__in=owned_company_ids)
        | Q(company_id__in=all_branch_company_ids)
        | Q(id__in=single_branch_ids)
    )


def user_can_access_branch(user, branch):
    if not branch:
        return False
    return user_accessible_branches(user, company=branch.company).filter(id=branch.id).exists()
