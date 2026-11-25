"""The services outside the application the workspace talks to: object storage for files, a payment
provider for invoices, a language model for reports.

A deployment without a service's setting never calls it, and the tests run without any. Each SDK
is imported inside the function that calls it, not with this module: anthropic alone loads some
3,500 modules and takes seconds, boto3 and stripe several hundred each. Imported with the module,
every process would pay that at start-up whether it ever calls them or not.
"""
import asyncio
import json
from decimal import Decimal

from app.settings import settings


async def delete_object(key: str) -> None:
    """Takes a deleted file's contents out of the bucket."""
    import boto3

    await asyncio.to_thread(boto3.client('s3').delete_object, Bucket=settings.S3_BUCKET, Key=key)


async def ask_for_payment(invoice_id: int, total: Decimal, currency: str) -> str:
    """Opens a payment for a sent invoice with the provider; gives back the provider's id of it."""
    import stripe

    client = stripe.StripeClient(settings.STRIPE_API_KEY)
    intent = await client.v1.payment_intents.create_async(params={
        'amount': int(total * 100), 'currency': currency.lower(), 'metadata': {'invoice': str(invoice_id)},
    })
    return intent.id


async def summarise(figures: dict) -> str:
    """Two sentences on what a report's figures say."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.beta.messages.create(
        model='claude-opus-5-5',
        max_tokens=1024,
        output_config={'effort': 'low'},
        betas=['server-side-fallback-2026-07-01'],
        fallbacks='default',
        messages=[{
            'role': 'user',
            'content': 'In two plain sentences, say what these figures of a team report show:\n'
                       + json.dumps(figures, default=str, sort_keys=True),
        }],
    )
    if response.stop_reason == 'refusal':
        return ''
    return ''.join(block.text for block in response.content if block.type == 'text')
