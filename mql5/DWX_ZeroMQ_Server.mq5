// DWX_ZeroMQ_Server.mq5
// QuantAI MT5 ZeroMQ bridge — PUSH 32768, PULL 32769, PUB 32770
// Requires ZMQ library for MQL5 (https://github.com/dingmaotu/mql-zmq)

#property service
#property copyright "QuantAI"
#property version   "1.0"

#include <Zmq/Zmq.mqh>

#define ZMQ_COMMAND_PORT 32768
#define ZMQ_CONFIRM_PORT 32769
#define ZMQ_TICK_PORT    32770
#define MAX_RETRIES      3
#define SLIPPAGE_POINTS  10

Context *context;
Socket  *push_socket;   // receives commands from Python
Socket  *pull_socket;   // sends confirmations to Python
Socket  *pub_socket;    // publishes ticks

string  last_error = "";

//+------------------------------------------------------------------+
void OnStart()
{
   context = new Context();
   push_socket = new Socket(*context, ZMQ_PULL);
   pull_socket = new Socket(*context, ZMQ_PUSH);
   pub_socket  = new Socket(*context, ZMQ_PUB);

   if(!push_socket.bind(StringFormat("tcp://*:%d", ZMQ_COMMAND_PORT)))
   {
      Print("Failed to bind PUSH port ", ZMQ_COMMAND_PORT);
      return;
   }
   if(!pull_socket.bind(StringFormat("tcp://*:%d", ZMQ_CONFIRM_PORT)))
   {
      Print("Failed to bind PULL port ", ZMQ_CONFIRM_PORT);
      return;
   }
   if(!pub_socket.bind(StringFormat("tcp://*:%d", ZMQ_TICK_PORT)))
   {
      Print("Failed to bind PUB port ", ZMQ_TICK_PORT);
      return;
   }

   Print("QuantAI ZeroMQ Server started on ports ", ZMQ_COMMAND_PORT, "-", ZMQ_TICK_PORT);

   while(!IsStopped())
   {
      ZmqMsg msg;
      push_socket.recv(msg, true);
      if(msg.size() > 0)
      {
         string request = msg.getData();
         string response = ProcessRequest(request);
         if(!pull_socket.send(response, true))
            Print("Failed to send confirmation");
      }
      PublishTicks();
      Sleep(10);
   }
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   delete push_socket;
   delete pull_socket;
   delete pub_socket;
   delete context;
   Print("QuantAI ZeroMQ Server stopped");
}

//+------------------------------------------------------------------+
string ProcessRequest(string json)
{
   ulong start_ms = GetTickCount64();
   string action = JsonGet(json, "action");

   if(action == "TRADE")
      return HandleTrade(json, start_ms);
   if(action == "ACCOUNT")
      return HandleAccount(start_ms);
   if(action == "DATA")
      return HandleData(json, start_ms);
   if(action == "POSITIONS")
      return HandlePositions(start_ms);
   if(action == "CLOSE_ALL")
      return HandleCloseAll(start_ms);

   return BuildError("Unknown action: " + action, start_ms);
}

//+------------------------------------------------------------------+
string HandleTrade(string json, ulong start_ms)
{
   string symbol  = JsonGet(json, "symbol");
   string type    = JsonGet(json, "type");
   double volume  = StringToDouble(JsonGet(json, "volume"));
   double sl      = StringToDouble(JsonGet(json, "sl"));
   double tp      = StringToDouble(JsonGet(json, "tp"));
   long   ticket  = (long)StringToInteger(JsonGet(json, "ticket"));

   string mt5_symbol = SymbolMap(symbol);
   if(type != "MODIFY" && type != "CLOSE")
   {
      if(!SymbolSelect(mt5_symbol, true))
         return BuildError("Symbol not found: " + symbol, start_ms);
   }

   MqlTradeRequest req = {};
   MqlTradeResult  res = {};
   req.symbol   = mt5_symbol;
   req.volume   = volume;
   req.deviation = SLIPPAGE_POINTS;
   req.magic    = 20260621;
   req.type_filling = ORDER_FILLING_IOC;

   if(type == "MODIFY" && ticket > 0)
   {
      if(!PositionSelectByTicket(ticket))
         return BuildError("Position not found: " + IntegerToString(ticket), start_ms);
      symbol = PositionGetString(POSITION_SYMBOL);
      req.symbol = symbol;
      req.action = TRADE_ACTION_SLTP;
      req.position = ticket;
      req.sl = sl;
      req.tp = tp;

      for(int retry = 0; retry < MAX_RETRIES; retry++)
      {
         if(OrderSend(req, res))
         {
            ulong latency = GetTickCount64() - start_ms;
            return StringFormat(
               "{\"status\":\"ok\",\"action\":\"TRADE\",\"type\":\"MODIFY\",\"symbol\":\"%s\","
               "\"ticket\":%d,\"sl\":%.5f,\"tp\":%.5f,\"slippage\":0.0,\"fill_rate\":1.0,"
               "\"latency_ms\":%d,\"retries\":%d}",
               symbol, ticket, sl, tp, (int)latency, retry);
         }
         last_error = res.comment;
         if(!IsRetryableRetcode(res.retcode))
            break;
         Sleep(200);
      }
      return BuildError("Modify failed: " + last_error, start_ms);
   }
   else if(type == "CLOSE" && ticket > 0)
   {
      if(!PositionSelectByTicket(ticket))
         return BuildError("Position not found: " + IntegerToString(ticket), start_ms);
      symbol = PositionGetString(POSITION_SYMBOL);
      req.symbol = symbol;
      req.action = TRADE_ACTION_DEAL;
      req.position = ticket;
      req.type = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      req.volume = PositionGetDouble(POSITION_VOLUME);
   }
   else if(type == "BUY" || type == "SELL")
   {
      req.action = TRADE_ACTION_DEAL;
      req.type   = (type == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      if(sl > 0) req.sl = sl;
      if(tp > 0) req.tp = tp;
   }
   else
      return BuildError("Invalid trade type: " + type, start_ms);

   double expected_price = 0;
   if(req.type == ORDER_TYPE_BUY)
      expected_price = SymbolInfoDouble(req.symbol, SYMBOL_ASK);
   else if(req.type == ORDER_TYPE_SELL)
      expected_price = SymbolInfoDouble(req.symbol, SYMBOL_BID);

   bool success = false;
   int retries_used = 0;
   for(int retry = 0; retry < MAX_RETRIES; retry++)
   {
      retries_used = retry;
      if(OrderSend(req, res))
      {
         success = true;
         break;
      }
      last_error = res.comment;
      if(IsRetryableRetcode(res.retcode))
      {
         Sleep(200);
         if(req.type == ORDER_TYPE_BUY)
            req.price = SymbolInfoDouble(mt5_symbol, SYMBOL_ASK);
         else if(req.type == ORDER_TYPE_SELL)
            req.price = SymbolInfoDouble(mt5_symbol, SYMBOL_BID);
         continue;
      }
      break;
   }

   ulong latency = GetTickCount64() - start_ms;
   double fill_price = res.price;
   double slippage = (expected_price > 0) ? MathAbs(fill_price - expected_price) : 0;

   if(success)
      return StringFormat(
         "{\"status\":\"ok\",\"action\":\"TRADE\",\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.4f,"
         "\"ticket\":%d,\"price\":%.5f,\"slippage\":%.5f,\"fill_rate\":1.0,\"latency_ms\":%d,\"retries\":%d}",
         symbol, type, volume, res.order, fill_price, slippage, (int)latency, retries_used);

   return BuildError("Trade failed: " + last_error, start_ms);
}

//+------------------------------------------------------------------+
string HandleAccount(ulong start_ms)
{
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double margin  = AccountInfoDouble(ACCOUNT_MARGIN);
   double free    = AccountInfoDouble(ACCOUNT_MARGIN_FREE);

   double gross_exposure = 0;
   double largest_pct = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      double vol = PositionGetDouble(POSITION_VOLUME);
      double price = PositionGetDouble(POSITION_PRICE_OPEN);
      double pos_value = vol * price;
      gross_exposure += pos_value;
      double pct = (equity > 0) ? pos_value / equity : 0;
      if(pct > largest_pct) largest_pct = pct;
   }

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"ACCOUNT\",\"equity\":%.2f,\"balance\":%.2f,"
      "\"margin\":%.2f,\"free_margin\":%.2f,\"gross_exposure\":%.2f,"
      "\"largest_position_pct\":%.4f,\"latency_ms\":%d}",
      equity, balance, margin, free, gross_exposure, largest_pct, (int)latency);
}

//+------------------------------------------------------------------+
string HandleData(string json, ulong start_ms)
{
   string symbol = JsonGet(json, "symbol");
   string tf_str = JsonGet(json, "timeframe");
   int count = (int)StringToInteger(JsonGet(json, "count"));
   if(count <= 0) count = 200;

   string mt5_symbol = SymbolMap(symbol);
   ENUM_TIMEFRAMES tf = TimeframeMap(tf_str);

   MqlRates rates[];
   int copied = CopyRates(mt5_symbol, tf, 0, count, rates);
   if(copied <= 0)
      return BuildError("Failed to copy rates for " + symbol, start_ms);

   string bars = "";
   for(int i = 0; i < copied; i++)
   {
      if(i > 0) bars += ",";
      bars += StringFormat(
         "{\"time\":%d,\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"volume\":%.0f}",
         rates[i].time, rates[i].open, rates[i].high, rates[i].low, rates[i].close, rates[i].tick_volume);
   }

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"DATA\",\"symbol\":\"%s\",\"timeframe\":\"%s\",\"count\":%d,"
      "\"bars\":[%s],\"latency_ms\":%d}",
      symbol, tf_str, copied, bars, (int)latency);
}

//+------------------------------------------------------------------+
string HandlePositions(ulong start_ms)
{
   string positions = "";
   int pos_count = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(pos_count > 0) positions += ",";
      string sym = PositionGetString(POSITION_SYMBOL);
      string dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      positions += StringFormat(
         "{\"ticket\":%d,\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.4f,"
         "\"price_open\":%.5f,\"sl\":%.5f,\"tp\":%.5f,\"profit\":%.2f}",
         ticket, sym, dir, PositionGetDouble(POSITION_VOLUME),
         PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_SL), PositionGetDouble(POSITION_TP),
         PositionGetDouble(POSITION_PROFIT));
      pos_count++;
   }

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"POSITIONS\",\"count\":%d,\"positions\":[%s],\"latency_ms\":%d}",
      pos_count, positions, (int)latency);
}

//+------------------------------------------------------------------+
string HandleCloseAll(ulong start_ms)
{
   int closed = 0;
   int failed = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      MqlTradeRequest req = {};
      MqlTradeResult  res = {};
      req.action   = TRADE_ACTION_DEAL;
      req.position = ticket;
      req.symbol   = PositionGetString(POSITION_SYMBOL);
      req.volume   = PositionGetDouble(POSITION_VOLUME);
      req.deviation = SLIPPAGE_POINTS;
      req.magic    = 20260621;
      req.type_filling = ORDER_FILLING_IOC;
      req.type = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

      bool ok = false;
      for(int retry = 0; retry < MAX_RETRIES; retry++)
      {
         if(OrderSend(req, res))
         {
            ok = true;
            break;
         }
         if(!IsRetryableRetcode(res.retcode))
            break;
         Sleep(200);
      }
      if(ok) closed++;
      else failed++;
   }

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"CLOSE_ALL\",\"closed\":%d,\"failed\":%d,\"latency_ms\":%d}",
      closed, failed, (int)latency);
}

//+------------------------------------------------------------------+
void PublishTicks()
{
   static ulong last_pub = 0;
   if(GetTickCount64() - last_pub < 1000) return;
   last_pub = GetTickCount64();

   string tick_data = "";
   int n = 0;
   for(int i = 0; i < SymbolsTotal(true); i++)
   {
      string sym = SymbolName(i, true);
      double bid = SymbolInfoDouble(sym, SYMBOL_BID);
      double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      if(n > 0) tick_data += ",";
      tick_data += StringFormat("{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f}", sym, bid, ask);
      n++;
      if(n >= 15) break;
   }
   if(n > 0)
   {
      pub_socket.send(StringFormat("{\"ticks\":[%s]}", tick_data), true);
   }
}

//+------------------------------------------------------------------+
string SymbolMap(string symbol)
{
   StringReplace(symbol, "/", "");
   return symbol;
}

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES TimeframeMap(string tf)
{
   if(tf == "M15") return PERIOD_M15;
   if(tf == "H1")  return PERIOD_H1;
   if(tf == "H4")  return PERIOD_H4;
   if(tf == "M5")  return PERIOD_M5;
   if(tf == "D1")  return PERIOD_D1;
   return PERIOD_M15;
}

//+------------------------------------------------------------------+
string JsonGet(string json, string key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   while(pos < StringLen(json) && (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == '"'))
      pos++;
   int end = pos;
   while(end < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, end);
      if(ch == '"' || ch == ',' || ch == '}') break;
      end++;
   }
   string val = StringSubstr(json, pos, end - pos);
   StringReplace(val, "\"", "");
   return val;
}

//+------------------------------------------------------------------+
bool IsRetryableRetcode(uint retcode)
{
   return retcode == TRADE_RETCODE_REQUOTE
       || retcode == TRADE_RETCODE_PRICE_CHANGED
       || retcode == TRADE_RETCODE_INVALID_PRICE
       || retcode == TRADE_RETCODE_INVALID_STOPS;
}

//+------------------------------------------------------------------+
string BuildError(string message, ulong start_ms)
{
   ulong latency = GetTickCount64() - start_ms;
   return StringFormat("{\"status\":\"error\",\"message\":\"%s\",\"latency_ms\":%d}", message, (int)latency);
}
