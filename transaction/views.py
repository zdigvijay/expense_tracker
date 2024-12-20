# transactions/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import datetime
from django.db.models.functions import TruncMonth ,TruncYear
import uuid

from .models import Transaction
from .serializers import TransactionSerializer
from category.models import Category
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 2
    page_size_query_param = 'page_size'
    max_page_size = 100

class TransactionListCreateView(APIView):
    """
    API endpoint for listing and creating transactions
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        # Filter transactions for the authenticated user\
        filters = {}
        for param, value in request.query_params.items():
            if param not in ['page', 'page_size']:
                filters[param] = value
        queryset = Transaction.objects.filter(user=request.user).order_by('-date')
        if filters:
            queryset = queryset.filter(**filters)
        else:
            pass
        # Pagination
        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(queryset, request)
        # Serialize and return paginated response
        serializer = TransactionSerializer(paginated_queryset, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        # Add the current user to the transaction data
        transaction_data = request.data.copy()
        transaction_data['user'] = request.user.id
        if 'date' not in transaction_data:
            transaction_data['date'] = timezone.now().date()
        serializer = TransactionSerializer(data=transaction_data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class TransactionDetailView(APIView):
    """
    API endpoint for retrieving, updating, and deleting a specific transaction
    """
    permission_classes = [IsAuthenticated]

    def get_object(self, pk, user):
        """
        Helper method to retrieve a transaction, ensuring user ownership
        """
        try:
            return Transaction.objects.get(id=pk, user=user)
        except Transaction.DoesNotExist:
            return None

    def get(self, request, pk):
        transaction = self.get_object(pk, request.user)
        if not transaction:
            return Response(
                {'error': 'Transaction not found or you do not have permission'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = TransactionSerializer(transaction)
        return Response(serializer.data)

    def put(self, request, pk):
        transaction = self.get_object(pk, request.user)
        if not transaction:
            return Response(
                {'error': 'Transaction not found or you do not have permission'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Prevent changing the user of the transaction
        update_data = request.data.copy()
        update_data.pop('user', None)
        
        serializer = TransactionSerializer(transaction, data=update_data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        transaction = self.get_object(pk, request.user)
        if not transaction:
            return Response(
                {'error': 'Transaction not found or you do not have permission'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        transaction.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class TransactionSummaryView(APIView):
    """
    API endpoint for getting transaction summaries
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get query parameters
        month = request.query_params.get('month',timezone.now().month)

        # Base queryset filtered by user
        queryset = Transaction.objects.filter(user=request.user,date__month=month)



        # Aggregate calculations
        summary = {
            'total_transactions': queryset.count(),
            'total_expense': queryset.filter(transaction_type='debit').aggregate(
                total=Sum('amount')
            )['total'] or 0,
            'total_income': queryset.filter(transaction_type='credit').aggregate(
                total=Sum('amount')
            )['total'] or 0,
            'net_amount': (
                queryset.filter(transaction_type='credit').aggregate(total=Sum('amount'))['total'] or 0
            ) - (
                queryset.filter(transaction_type='debit').aggregate(total=Sum('amount'))['total'] or 0
            ),
            'transactions_by_category': list(
                queryset.values('category__name', 'transaction_type')
                .annotate(
                    total_amount=Sum('amount'),
                    count=Count('id')
                )
                .order_by('-total_amount')
            )
        }

        return Response(summary)




class CategoryTransactionSummaryView(APIView):
    """
    API endpoint for getting transaction summary for a specific category.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        """
        Retrieve transaction summary for a specific category.

        URL Parameters:
        - category_uuid: UUID of the category to filter transactions.

        Query Parameters (optional):
        - year: Specific year to filter transactions (default: current year).
        - month: Specific month to filter transactions (default: all months).
        """

        # Get optional query parameters
        year = request.query_params.get('year', timezone.now().year)
        month = request.query_params.get('month')

        # Validate year
        try:
            year = int(year)
            if year < 1000 or year > 9999:
                raise ValueError("Invalid year")
        except ValueError:
            return Response({'error': 'Invalid year parameter'}, status=400)

        # Validate month if provided
        if month:
            try:
                month = int(month)
                if month < 1 or month > 12:
                    raise ValueError("Invalid month")
            except ValueError:
                return Response({'error': 'Invalid month parameter'}, status=400)

        # Base queryset filtered by user and specific category
        queryset = Transaction.objects.filter(
            user=request.user,
            category__uuid=id,  # Assuming category has a UUID field
            date__year=year
        )

        # Optional month filter
        if month:
            queryset = queryset.filter(date__month=month)

        # Calculate category-specific transaction summary
        
        summary = {
            'category_uuid': id,
            'total_transactions': queryset.count(),
            'total_amount': queryset.aggregate(total=Sum('amount'))['total'] or 0,
            'transactions_by_type': {
                'debit': (
                    queryset.filter(transaction_type='debit')
                    .aggregate(
                        total_amount=Sum('amount'),
                        count=Count('id')
                    )
                ),
                'credit': (
                    queryset.filter(transaction_type='credit')
                    .aggregate(
                        total_amount=Sum('amount'),
                        count=Count('id')
                    )
                )
            },
            'transactions_details': list(
                queryset.values(
                    'id', 
                    'amount', 
                    'date', 
                    'description', 
                    'transaction_type'
                ).order_by('-date')  # Order transactions by date descending
            )
        }

        return Response(summary,content_type='applcation/json')
